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
        entries = []
        for postcard_id, year in enumerate(
                ("1920", "ca. 1910", "", "1910-1915", "unknown era"), start=1):
            entries.append({
                "id": postcard_id,
                "uuid": f"00000000-0000-4000-8000-{postcard_id:012d}",
                "front_image_path": "/f.jpg", "back_image_path": "",
                "year": year, "description": "", "tags": [],
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            })
        self.db.import_data({
            "format": "picture-postcard-manager", "schema_version": 6,
            "exported_at": "2026-01-02T00:00:00+00:00", "postcards": entries,
        }, mode="replace")

    def years(self, query=None, **kwargs):
        return [p["year"] for p in self.db.list(query, **kwargs)]

    def test_default_is_newest_first(self):
        self.assertEqual(self.years(),
                         ["unknown era", "1910-1915", "", "ca. 1910", "1920"])

    def test_free_text_years_sort_by_first_number(self):
        self.assertEqual(self.years(sort="year"),
                         ["1910-1915", "ca. 1910", "1920", "unknown era", ""])
        self.assertEqual(self.years(sort="year", direction="desc"),
                         ["1920", "ca. 1910", "1910-1915", "unknown era", ""])

    def test_sort_by_updated(self):
        updated = [p["updated_at"] for p in self.db.list(sort="updated")]
        self.assertEqual(updated, sorted(updated))

    def test_sort_combines_with_search(self):
        self.assertEqual(self.years("19", sort="year"),
                         ["1910-1915", "ca. 1910", "1920"])

    def test_invalid_sort_is_rejected(self):
        for sort in ("id; DROP TABLE postcards", "place", "region"):
            with self.subTest(sort=sort):
                with self.assertRaisesRegex(ValueError, "sort"):
                    self.db.list(sort=sort)
        with self.assertRaisesRegex(ValueError, "dir"):
            self.db.list(sort="year", direction="sideways")

    def test_sort_combines_with_pagination(self):
        # Pages of a sorted listing continue the same global order.
        self.assertEqual(self.years(sort="year", limit=2),
                         ["1910-1915", "ca. 1910"])
        self.assertEqual(self.years(sort="year", limit=2, offset=2),
                         ["1920", "unknown era"])
        self.assertEqual(self.years(sort="year", limit=2, offset=4), [""])
        self.assertEqual(self.years(sort="year", limit=2, offset=5), [])
        self.assertEqual(self.years(sort="year", direction="desc", offset=1),
                         ["ca. 1910", "1910-1915", "unknown era", ""])

    def test_invalid_pagination_is_rejected_with_sort(self):
        for kwargs in ({"limit": 0}, {"limit": "2"}, {"offset": -1}, {"offset": None}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    self.db.list(sort="year", **kwargs)


class SortingApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = make_server("127.0.0.1", 0, str(Path(self.tmp.name) / "test.db"))
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        db = self.server.RequestHandlerClass.db
        for year in ("1930", "1910", "1920"):
            db.create({"front_image_path": "/f.jpg", "year": year})

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
        status, items = self.get("/api/postcards?sort=year")
        self.assertEqual((status, [p["year"] for p in items]),
                         (200, ["1910", "1920", "1930"]))
        status, items = self.get("/api/postcards?sort=year&dir=desc")
        self.assertEqual([p["year"] for p in items], ["1930", "1920", "1910"])
        status, items = self.get("/api/postcards")
        self.assertEqual([p["year"] for p in items], ["1920", "1910", "1930"])

    def test_sort_combines_with_search(self):
        status, items = self.get("/api/postcards?q=192&sort=year")
        self.assertEqual((status, [p["year"] for p in items]), (200, ["1920"]))

    def test_invalid_sort_parameters(self):
        for query in ("sort=id", "sort=year&dir=up", "sort=unknown",
                      "sort=place", "sort=region",
                      "sort=year&limit=0", "sort=year&offset=-1"):
            with self.subTest(query=query):
                status, body = self.get(f"/api/postcards?{query}")
                self.assertEqual(status, 400)
                self.assertIn("error", body)

    def test_sorted_pages_continue_in_order(self):
        status, items = self.get("/api/postcards?sort=year&limit=2&offset=0")
        self.assertEqual((status, [p["year"] for p in items]),
                         (200, ["1910", "1920"]))
        status, items = self.get("/api/postcards?sort=year&limit=2&offset=2")
        self.assertEqual((status, [p["year"] for p in items]), (200, ["1930"]))


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
