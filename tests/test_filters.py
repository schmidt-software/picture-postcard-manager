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


class FilterUiTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is optional")
    def test_javascript_runtime(self):
        result = subprocess.run(
            [shutil.which("node"), str(ROOT / "tests/filters_runtime.js")],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
