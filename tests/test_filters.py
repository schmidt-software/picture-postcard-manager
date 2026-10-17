"""Tests for the postcard overview filters."""

import json
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from app.db import Database
from app.server import make_server

ROOT = Path(__file__).resolve().parents[1]


class FilterDbTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        for year, tags in (
            ("1910", ["street", "color", "Berlin"]),
            ("1920", ["street", "Berlin"]),
            ("1910", ["Munich"]),
            ("", ["color"]),
        ):
            self.db.create({"front_image_path": "/f.jpg", "year": year,
                            "tags": tags})

    def ids(self, **kwargs):
        return [p["id"] for p in self.db.list(**kwargs)]

    def test_single_filters(self):
        self.assertEqual(self.ids(filters={"year": "1910"}), [3, 1])
        self.assertEqual(self.ids(filters={"tag": "color"}), [4, 1])
        self.assertEqual(self.ids(filters={"tag": "Berlin"}), [2, 1])

    def test_filters_are_exact_not_substrings(self):
        self.assertEqual(self.ids(filters={"year": "191"}), [])
        self.assertEqual(self.ids(filters={"tag": "stre"}), [])

    def test_filters_combine_with_each_other_and_search(self):
        self.assertEqual(self.ids(filters={"tag": "Berlin", "year": "1910"}), [1])
        self.assertEqual(self.ids(query="street", filters={"year": "1920"}), [2])
        self.assertEqual(self.ids(query="Munich", filters={"tag": "color"}), [])

    def test_empty_filter_values_match_empty_fields(self):
        self.assertEqual(self.ids(filters={"year": ""}), [4])

    def test_invalid_filters_are_rejected(self):
        for field in ("id", "place", "region"):
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "unknown filter"):
                    self.db.list(filters={field: "1"})
        with self.assertRaisesRegex(ValueError, "must be a string"):
            self.db.list(filters={"year": 5})

    def test_filter_values(self):
        values = self.db.filter_values()
        self.assertEqual(values["year"], ["1910", "1920"])
        self.assertEqual(values["tag"], ["Berlin", "color", "Munich", "street"])
        self.assertNotIn("place", values)
        self.assertNotIn("region", values)

    def test_filters_combine_with_sorting_and_pagination(self):
        # Filtered result sorted by year descending: id 2 (1920) before id 1
        # (1910); the page window cuts the sorted, filtered result, so
        # consecutive pages continue the same global order.
        self.assertEqual(
            self.ids(filters={"tag": "Berlin"}, sort="year", direction="desc"),
            [2, 1])
        self.assertEqual(
            self.ids(filters={"tag": "Berlin"}, sort="year", direction="desc",
                     limit=1),
            [2])
        self.assertEqual(
            self.ids(filters={"tag": "Berlin"}, sort="year", direction="desc",
                     limit=1, offset=1),
            [1])
        # Search, filter and sort combine: "street" matches ids 1 and 2, the
        # year filter keeps id 1, sorting is a no-op on one row but accepted.
        self.assertEqual(
            self.ids(query="street", filters={"year": "1910"}, sort="year"),
            [1])

    def test_filtered_sorted_count_matches_listing(self):
        filters = {"tag": "Berlin"}
        listed = self.db.list(filters=filters, sort="year", direction="desc")
        self.assertEqual(self.db.count(filters=filters), len(listed))


class MultiTagFilterDbTest(unittest.TestCase):
    """AND semantics for multi-tag filtering (issue #52)."""

    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        for year, tags in (
            ("1910", ["Vienna", "Night", "color"]),       # 1
            ("1920", ["Vienna", "Night"]),                # 2
            ("1910", ["Vienna"]),                         # 3
            ("1930", ["vienna", "night"]),                # 4 (case variants)
            ("1940", ["Caf\u00e9 \u00c9t\u00e9", "\u6771\u4eac", "\U0001f30d"]),  # 5 (Unicode)
            ("1950", ['a"b] OR 1=1 --', "x' OR '1'='1", "%", "_"]),  # 6 (hostile)
            ("1960", []),                                 # 7 (no tags)
        ):
            self.db.create({"front_image_path": "/f.jpg", "year": year,
                            "tags": tags})

    def ids(self, **kwargs):
        return [p["id"] for p in self.db.list(**kwargs)]

    def test_zero_tags_impose_no_restriction(self):
        self.assertEqual(self.ids(filters={"tag": []}),
                         [7, 6, 5, 4, 3, 2, 1])

    def test_single_tag_as_string_or_one_element_list(self):
        self.assertEqual(self.ids(filters={"tag": "Vienna"}), [3, 2, 1])
        self.assertEqual(self.ids(filters={"tag": ["Vienna"]}), [3, 2, 1])

    def test_two_tags_require_both(self):
        self.assertEqual(self.ids(filters={"tag": ["Vienna", "Night"]}), [2, 1])
        # Order of the requested tags never changes the result.
        self.assertEqual(self.ids(filters={"tag": ["Night", "Vienna"]}), [2, 1])

    def test_many_tags_card_may_have_extras(self):
        # Card 1 carries "color" beyond the requested tags and still matches.
        self.assertEqual(
            self.ids(filters={"tag": ["Vienna", "Night", "color"]}), [1])
        self.assertEqual(
            self.ids(filters={"tag": ["Vienna", "Night", "color", "missing"]}), [])

    def test_duplicate_requested_tags_are_deduplicated(self):
        self.assertEqual(
            self.ids(filters={"tag": ["Vienna", "Vienna", "Night", "Vienna"]}),
            self.ids(filters={"tag": ["Vienna", "Night"]}))

    def test_matching_is_case_sensitive(self):
        self.assertEqual(self.ids(filters={"tag": ["vienna", "night"]}), [4])
        self.assertEqual(self.ids(filters={"tag": ["Vienna", "night"]}), [])

    def test_unicode_tags_match_exactly(self):
        self.assertEqual(
            self.ids(filters={"tag": ["Caf\u00e9 \u00c9t\u00e9", "\u6771\u4eac"]}), [5])
        self.assertEqual(self.ids(filters={"tag": ["\U0001f30d"]}), [5])

    def test_hostile_values_are_parameterized_not_injected(self):
        # SQL-like and JSON-like fragments are matched as literal tag text.
        self.assertEqual(self.ids(filters={"tag": ['a"b] OR 1=1 --']}), [6])
        self.assertEqual(
            self.ids(filters={"tag": ["x' OR '1'='1", "%"]}), [6])
        # LIKE wildcards have no meaning: "%" matches only the literal tag.
        self.assertEqual(self.ids(filters={"tag": ["%"]}), [6])
        self.assertEqual(self.ids(filters={"tag": ["_"]}), [6])
        # A raw-JSON-substring match would also hit card 6 for '"'; exact
        # element matching must not.
        self.assertEqual(self.ids(filters={"tag": ['"']}), [])

    def test_blank_and_malformed_tag_filters_are_rejected(self):
        for bad in ("", "   ", [""], ["Vienna", " "], [5], [None], 5, {}):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    self.db.list(filters={"tag": bad})

    def test_multi_tag_combines_with_search_sort_and_pagination(self):
        matches = self.ids(filters={"tag": ["Vienna", "Night"]},
                           sort="year", direction="asc")
        self.assertEqual(matches, [1, 2])
        self.assertEqual(
            self.ids(filters={"tag": ["Vienna", "Night"]}, sort="year",
                     direction="asc", limit=1, offset=1), [2])
        self.assertEqual(
            self.ids(query="color", filters={"tag": ["Vienna", "Night"]}), [1])

    def test_count_reflects_the_complete_multi_tag_filter(self):
        self.assertEqual(self.db.count(filters={"tag": ["Vienna", "Night"]}), 2)
        self.assertEqual(
            self.db.count(filters={"tag": ["Vienna", "Vienna", "Night"]}), 2)
        self.assertEqual(self.db.count(filters={"tag": []}), 7)


class FilterApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = make_server("127.0.0.1", 0, str(Path(self.tmp.name) / "test.db"))
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        db = self.server.RequestHandlerClass.db
        db.create({"front_image_path": "/f.jpg", "year": "1910",
                   "tags": ["alte Ansicht", "Berlin, Mitte"]})
        db.create({"front_image_path": "/f.jpg", "year": "1920", "tags": ["Munich"]})
        db.create({"front_image_path": "/f.jpg", "year": "1905",
                   "tags": ["alte Ansicht", "Berlin, Mitte"]})
        db.create({"front_image_path": "/f.jpg", "year": "1925",
                   "tags": ["alte Ansicht", "Berlin, Mitte"]})

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.server.RequestHandlerClass.db.close()
        self.tmp.cleanup()

    def get(self, path):
        try:
            with urllib.request.urlopen(self.base + path) as res:
                return res.status, json.loads(res.read())
        except urllib.error.HTTPError as err:
            with err:
                return err.code, json.loads(err.read())

    def test_filtered_listing(self):
        tag = urllib.parse.quote("Berlin, Mitte")
        status, items = self.get(f"/api/postcards?tag={tag}")
        self.assertEqual((status, [p["id"] for p in items]), (200, [4, 3, 1]))
        status, items = self.get(f"/api/postcards?tag={tag}&year=1910")
        self.assertEqual((status, [p["id"] for p in items]), (200, [1]))
        status, items = self.get("/api/postcards?q=Mun&year=1920")
        self.assertEqual((status, [p["id"] for p in items]), (200, [2]))
        status, items = self.get("/api/postcards?year=1999")
        self.assertEqual((status, items), (200, []))

    def test_filtered_sorted_paged_listing(self):
        # The filter keeps ids 1, 3, 4; sorted by year ascending the global
        # order is 3 (1905), 1 (1910), 4 (1925). Pages of one row each walk
        # that order without gaps or duplicates.
        tag = urllib.parse.quote("Berlin, Mitte")
        base = f"/api/postcards?tag={tag}&sort=year&dir=asc"
        status, items = self.get(base)
        self.assertEqual((status, [p["id"] for p in items]), (200, [3, 1, 4]))
        pages = []
        for offset in range(3):
            status, items = self.get(f"{base}&limit=1&offset={offset}")
            self.assertEqual(status, 200)
            pages.extend(p["id"] for p in items)
        self.assertEqual(pages, [3, 1, 4])
        status, items = self.get(f"{base}&limit=1&offset=3")
        self.assertEqual((status, items), (200, []))
        # Search narrows the filtered, sorted result further.
        other = urllib.parse.quote("alte Ansicht")
        status, items = self.get(
            f"/api/postcards?q=Berlin&tag={other}&sort=year&dir=desc")
        self.assertEqual((status, [p["id"] for p in items]), (200, [4, 1, 3]))
        # Invalid sort values are rejected with filters present, too.
        status, _ = self.get(f"/api/postcards?tag={tag}&sort=evil")
        self.assertEqual(status, 400)

    def test_obsolete_filter_and_sort_parameters_are_rejected(self):
        """Removed place/region parameters return the validation error."""
        for query in ("place=Berlin", "region=Bavaria", "sort=place",
                      "sort=region", "place=X&year=1910"):
            with self.subTest(query=query):
                status, body = self.get(f"/api/postcards?{query}")
                self.assertEqual(status, 400)
                self.assertIn("error", body)

    def test_filter_values_endpoint(self):
        status, values = self.get("/api/postcards/filters")
        self.assertEqual(status, 200)
        self.assertEqual(values["year"], ["1905", "1910", "1920", "1925"])
        self.assertEqual(values["tag"], ["alte Ansicht", "Berlin, Mitte", "Munich"])
        self.assertNotIn("place", values)
        self.assertNotIn("region", values)

    def test_repeated_tag_parameters_use_and_semantics(self):
        """Repeated tag parameters narrow the result (issue #52)."""
        one = urllib.parse.quote("alte Ansicht")
        two = urllib.parse.quote("Berlin, Mitte")
        status, items = self.get(f"/api/postcards?tag={one}&tag={two}")
        self.assertEqual((status, [p["id"] for p in items]), (200, [4, 3, 1]))
        status, items = self.get(f"/api/postcards?tag={one}&tag=Munich")
        self.assertEqual((status, items), (200, []))
        # Duplicate values are canonicalized and do not change the result.
        status, items = self.get(f"/api/postcards?tag={one}&tag={one}&tag={two}")
        self.assertEqual((status, [p["id"] for p in items]), (200, [4, 3, 1]))
        # Pagination and count reflect the complete multi-tag filter.
        base = f"/api/postcards?tag={one}&tag={two}&sort=year&dir=asc"
        pages = []
        for offset in range(3):
            status, items = self.get(f"{base}&limit=1&offset={offset}")
            self.assertEqual(status, 200)
            pages.extend(p["id"] for p in items)
        self.assertEqual(pages, [3, 1, 4])
        status, items = self.get(f"{base}&limit=1&offset=3")
        self.assertEqual((status, items), (200, []))

    def test_blank_tag_parameters_are_rejected(self):
        """Blank tag parameters return the documented HTTP 400 validation."""
        for query in ("tag=", "tag=%20", "tag=Munich&tag=", "tag=&tag=Munich"):
            with self.subTest(query=query):
                status, body = self.get(f"/api/postcards?{query}")
                self.assertEqual(status, 400)
                self.assertIn("error", body)


class FilterUiTest(unittest.TestCase):
    def test_multi_tag_filter_markup(self):
        """Accessible multi-tag filter control (issue #52)."""
        html = (ROOT / "app" / "static" / "index.html").read_text()
        # Chip list with a localized accessible name, add-select and clear-all.
        self.assertRegex(html, r'<ul id="filter-tag-list"[^>]*class="tag-list"')
        self.assertRegex(
            html, r'<ul id="filter-tag-list"[^>]*data-i18n-aria-label="selectedTagFilters"')
        self.assertRegex(
            html, r'<select id="filter-tag"[^>]*data-i18n-aria-label="addTagFilter"')
        self.assertRegex(html, r'<button type="button" id="filter-tag-clear"')
        # Live region for add/remove/clear announcements, visually hidden.
        self.assertRegex(html, r'<span id="filter-tag-status" class="visually-hidden"'
                               r' role="status" aria-live="polite">')
        # The single-select tag label of the old UI is gone.
        self.assertNotRegex(html, r'<label><span data-i18n="tag">')

    def test_multi_tag_filter_css(self):
        css = (ROOT / "app" / "static" / "style.css").read_text()
        # Chips and controls wrap without horizontal overflow.
        self.assertRegex(css, r"\.filter-tag-controls \{[^}]*flex-wrap: wrap")
        self.assertRegex(css, r"\.filter-tags \{[^}]*max-width: 100%")
        # Forced-colors mode keeps the fieldset border visible.
        self.assertRegex(css, r"forced-colors: active[^@]*\.filter-tags \{[^}]*CanvasText")
        # Narrow screens let the add-select take the full row.
        self.assertRegex(css, r"max-width: 480px[^@]*\.filter-tags \{[^}]*flex-basis")

    def test_translations(self):
        js = (ROOT / "app" / "static" / "languages.js").read_text()
        for key in ("filterTags:", "selectedTagFilters:", "addTagFilter:",
                    "clearTagFilters:", "removeTagFilter:", "tagFilterAdded:",
                    "tagFilterRemoved:", "tagFilterCleared:", "filterTagAdd:"):
            self.assertEqual(js.count(key), 2, f"{key} must exist in both languages")

    @unittest.skipUnless(shutil.which("node"), "Node.js is optional")
    def test_javascript_runtime(self):
        result = subprocess.run(
            [shutil.which("node"), str(ROOT / "tests/filters_runtime.js")],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
