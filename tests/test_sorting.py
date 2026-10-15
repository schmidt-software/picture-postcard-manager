"""Tests for user-controlled sorting of the postcard overview."""

import json
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from app.db import Database
from app.server import make_server

ROOT = Path(__file__).resolve().parents[1]


class SortingDbTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        for place, region, year in (
            ("munich", "Bavaria", "1920"),
            ("Berlin", "", "ca. 1910"),
            ("", "brandenburg", ""),
            ("Ahrental", "Tyrol", "1910-1915"),
            ("Zürich", "Zurich", "unknown era"),
        ):
            self.db.create({"front_image_path": "/f.jpg", "place": place,
                            "region": region, "year": year})

    def places(self, **kwargs):
        return [p["place"] for p in self.db.list(**kwargs)]

    def test_default_is_newest_first(self):
        self.assertEqual(self.places(), ["Zürich", "Ahrental", "", "Berlin", "munich"])

    def test_sort_by_place_is_case_insensitive_with_empty_last(self):
        self.assertEqual(self.places(sort="place"),
                         ["Ahrental", "Berlin", "munich", "Zürich", ""])
        self.assertEqual(self.places(sort="place", direction="desc"),
                         ["Zürich", "munich", "Berlin", "Ahrental", ""])

    def test_sort_by_region(self):
        regions = [p["region"] for p in self.db.list(sort="region")]
        self.assertEqual(regions, ["Bavaria", "brandenburg", "Tyrol", "Zurich", ""])

    def test_free_text_years_sort_by_first_number(self):
        years = [p["year"] for p in self.db.list(sort="year")]
        self.assertEqual(years, ["1910-1915", "ca. 1910", "1920", "unknown era", ""])
        years = [p["year"] for p in self.db.list(sort="year", direction="desc")]
        self.assertEqual(years, ["1920", "ca. 1910", "1910-1915", "unknown era", ""])

    def test_sort_by_updated(self):
        updated = [p["updated_at"] for p in self.db.list(sort="updated")]
        self.assertEqual(updated, sorted(updated))

    def test_sort_combines_with_search(self):
        self.assertEqual([p["place"] for p in self.db.list("19", sort="year")],
                         ["Ahrental", "Berlin", "munich"])

    def test_invalid_sort_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "sort"):
            self.db.list(sort="id; DROP TABLE postcards")
        with self.assertRaisesRegex(ValueError, "dir"):
            self.db.list(sort="place", direction="sideways")

    def test_sort_combines_with_pagination(self):
        # Pages of a sorted listing continue the same global order.
        self.assertEqual(self.places(sort="place", limit=2), ["Ahrental", "Berlin"])
        self.assertEqual(self.places(sort="place", limit=2, offset=2),
                         ["munich", "Zürich"])
        self.assertEqual(self.places(sort="place", limit=2, offset=4), [""])
        self.assertEqual(self.places(sort="place", limit=2, offset=5), [])
        self.assertEqual(self.places(sort="place", direction="desc", offset=1),
                         ["munich", "Berlin", "Ahrental", ""])

    def test_invalid_pagination_is_rejected_with_sort(self):
        for kwargs in ({"limit": 0}, {"limit": "2"}, {"offset": -1}, {"offset": None}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    self.db.list(sort="place", **kwargs)


class SortingApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = make_server("127.0.0.1", 0, str(Path(self.tmp.name) / "test.db"))
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        db = self.server.RequestHandlerClass.db
        for place in ("Munich", "Berlin", "Augsburg"):
            db.create({"front_image_path": "/f.jpg", "place": place})

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

    def test_sorted_listing(self):
        status, items = self.get("/api/postcards?sort=place")
        self.assertEqual((status, [p["place"] for p in items]),
                         (200, ["Augsburg", "Berlin", "Munich"]))
        status, items = self.get("/api/postcards?sort=place&dir=desc")
        self.assertEqual([p["place"] for p in items], ["Munich", "Berlin", "Augsburg"])
        status, items = self.get("/api/postcards")
        self.assertEqual([p["place"] for p in items], ["Augsburg", "Berlin", "Munich"])

    def test_sort_combines_with_search(self):
        status, items = self.get("/api/postcards?q=u&sort=place")
        self.assertEqual((status, [p["place"] for p in items]),
                         (200, ["Augsburg", "Munich"]))

    def test_invalid_sort_parameters(self):
        for query in ("sort=id", "sort=place&dir=up", "sort=unknown",
                      "sort=place&limit=0", "sort=place&offset=-1"):
            with self.subTest(query=query):
                status, body = self.get(f"/api/postcards?{query}")
                self.assertEqual(status, 400)
                self.assertIn("error", body)

    def test_sorted_pages_continue_in_order(self):
        status, items = self.get("/api/postcards?sort=place&limit=2&offset=0")
        self.assertEqual((status, [p["place"] for p in items]),
                         (200, ["Augsburg", "Berlin"]))
        status, items = self.get("/api/postcards?sort=place&limit=2&offset=2")
        self.assertEqual((status, [p["place"] for p in items]), (200, ["Munich"]))


class SortingUiTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is optional")
    def test_javascript_runtime(self):
        result = subprocess.run(
            [shutil.which("node"), str(ROOT / "tests/sorting_runtime.js")],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
