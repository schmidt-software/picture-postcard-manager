import json
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path

from app.db import Database, SCHEMA_VERSION
from app.server import make_server

ROOT = Path(__file__).resolve().parents[1]

V2_SCHEMA = """
CREATE TABLE postcards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
    front_image_path TEXT NOT NULL DEFAULT '', back_image_path TEXT NOT NULL DEFAULT '',
    place TEXT NOT NULL DEFAULT '', region TEXT NOT NULL DEFAULT '',
    year TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""


class TagsDatabaseTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)

    def create(self, **extra):
        return self.db.create({"front_image_path": "/f.jpg", **extra})

    def test_default_is_empty_list(self):
        self.assertEqual(self.create()["tags"], [])

    def test_trim_order_dedup_and_unicode(self):
        tags = ["  Berlin, Mitte ", "Ünï ✉", "Berlin, Mitte", "berlin, mitte", '"quoted"', "a\\b"]
        item = self.create(tags=tags)
        self.assertEqual(item["tags"],
                         ["Berlin, Mitte", "Ünï ✉", "berlin, mitte", '"quoted"', "a\\b"])
        self.assertEqual(self.db.get(item["id"]), item)

    def test_invalid_tags_rejected(self):
        for bad in ("a", None, 1, {"a": 1}, [1], [None], [["a"]], [""], ["a", "  \t"]):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "tags must"):
                self.create(tags=bad)
        self.assertEqual(self.db.list(), [])

    def test_partial_update_and_clear(self):
        item = self.create(tags=["a", "b"])
        self.assertEqual(self.db.update(item["id"], {"place": "X"})["tags"], ["a", "b"])
        self.assertEqual(self.db.update(item["id"], {"tags": ["c"]})["tags"], ["c"])
        self.assertEqual(self.db.update(item["id"], {"tags": []})["tags"], [])
        with self.assertRaises(ValueError):
            self.db.update(item["id"], {"tags": ["", "x"]})
        self.assertEqual(self.db.get(item["id"])["tags"], [])

    def test_search_matches_decoded_tag_text(self):
        a = self.create(tags=["Café, Wien", "Zürich"])
        b = self.create(tags=['say "hi"'])
        c = self.create(description="plain", tags=[])
        ids = lambda q: [p["id"] for p in self.db.list(q)]
        self.assertEqual(ids("Café, Wien"), [a["id"]])
        self.assertEqual(ids("rich"), [a["id"]])
        self.assertEqual(ids('say "hi"'), [b["id"]])
        self.assertEqual(ids('\\"'), [])
        self.assertEqual(ids("["), [])
        self.assertEqual(ids("plain"), [c["id"]])

    def test_roundtrip_and_old_import_versions(self):
        item = self.create(tags=["x, y", "ü"])
        export = self.db.export_data()
        self.assertEqual(export["schema_version"], 3)
        self.assertEqual(export["postcards"][0]["tags"], ["x, y", "ü"])
        self.db.import_data(export, "replace")
        self.assertEqual(self.db.get(item["id"]), item)
        for version in (1, 2):
            payload = {"schema_version": version, "postcards": [{"front_image_path": "/o.jpg"}]}
            self.db.import_data(payload, "replace")
            self.assertEqual(self.db.list()[0]["tags"], [])

    def test_malformed_import_is_atomic(self):
        item = self.create(tags=["keep"])
        for bad in ([{"front_image_path": "/a.jpg", "tags": ["ok"]},
                     {"front_image_path": "/b.jpg", "tags": [" "]}],
                    [{"front_image_path": "/a.jpg", "tags": ["ok"]},
                     {"front_image_path": "/b.jpg", "tags": "no"}]):
            for mode in ("append", "replace"):
                with self.assertRaisesRegex(ValueError, "postcard 2: tags must"):
                    self.db.import_data({"postcards": bad}, mode)
                self.assertEqual(self.db.list(), [item])


class TagsMigrationTest(unittest.TestCase):
    def test_version_2_database_migrates_without_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v2.db"
            with closing(sqlite3.connect(path)) as conn, conn:
                conn.executescript(V2_SCHEMA)
                conn.execute("PRAGMA user_version = 2")
                conn.execute(
                    "INSERT INTO postcards VALUES (3, 't', 'n', '/f', '/b', 'P', 'R', '1900', 'D', 'c', 'u')")
            db = Database(path)
            self.addCleanup(db.close)
            item = db.get(3)
            self.assertEqual((item["tags"], item["place"], item["created_at"]), ([], "P", "c"))
            self.assertEqual(db.update(3, {"tags": ["new"]})["tags"], ["new"])
            with closing(sqlite3.connect(path)) as conn:
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
            reopened = Database(path)
            self.addCleanup(reopened.close)
            self.assertEqual(reopened.get(3)["tags"], ["new"])


class TagsApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = make_server("127.0.0.1", 0, str(Path(self.tmp.name) / "t.db"))
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.server.RequestHandlerClass.db.close)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, data=None):
        req = urllib.request.Request(
            self.base + path, method=method, headers={"Content-Type": "application/json"},
            data=json.dumps(data).encode() if data is not None else None)
        try:
            with urllib.request.urlopen(req) as res:
                return res.status, json.loads(res.read() or b"null")
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read())

    def test_api_flow(self):
        status, item = self.request("POST", "/api/postcards",
                                    {"front_image_path": "/f", "tags": [" a,b ", "ü"]})
        self.assertEqual((status, item["tags"]), (201, ["a,b", "ü"]))
        status, body = self.request("POST", "/api/postcards", {"front_image_path": "/f", "tags": [""]})
        self.assertEqual(status, 400)
        self.assertIn("tags", body["error"])
        _, found = self.request("GET", "/api/postcards?q=a%2Cb")
        self.assertEqual([p["id"] for p in found], [item["id"]])
        _, same = self.request("PUT", f"/api/postcards/{item['id']}", {"place": "P"})
        self.assertEqual(same["tags"], ["a,b", "ü"])
        _, cleared = self.request("PUT", f"/api/postcards/{item['id']}", {"tags": []})
        self.assertEqual(cleared["tags"], [])
        self.assertEqual(self.request("POST", "/api/import", {"postcards": [
            {"front_image_path": "/x", "tags": [5]}]})[0], 400)


class TagsRuntimeTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is optional")
    def test_tag_editor_runtime(self):
        result = subprocess.run(
            [shutil.which("node"), str(ROOT / "tests" / "tags_runtime.js")],
            cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
