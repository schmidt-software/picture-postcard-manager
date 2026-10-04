import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from app.server import make_server


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = make_server("127.0.0.1", 0, str(Path(self.tmp.name) / "test.db"))
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.server.RequestHandlerClass.db.close()
        self.tmp.cleanup()

    def request(self, method, path, data=None, raw=None):
        body = raw if raw is not None else (json.dumps(data).encode() if data is not None else None)
        req = urllib.request.Request(self.base + path, data=body, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as res:
                content = res.read()
                return res.status, json.loads(content) if content else None
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read())

    def test_crud(self):
        status, created = self.request("POST", "/api/postcards", {"title": "Berlin", "notes": "1910"})
        self.assertEqual(status, 201)
        pid = created["id"]

        status, items = self.request("GET", "/api/postcards")
        self.assertEqual([p["title"] for p in items], ["Berlin"])

        status, updated = self.request("PUT", f"/api/postcards/{pid}", {"title": "Munich"})
        self.assertEqual(updated["title"], "Munich")
        self.assertEqual(updated["notes"], "1910")

        status, found = self.request("GET", "/api/postcards?q=Mun")
        self.assertEqual(len(found), 1)

        status, _ = self.request("DELETE", f"/api/postcards/{pid}")
        self.assertEqual(status, 204)
        status, _ = self.request("GET", f"/api/postcards/{pid}")
        self.assertEqual(status, 404)

    def test_export_import_roundtrip(self):
        self.request("POST", "/api/postcards", {"title": "A"})
        self.request("POST", "/api/postcards", {"title": "B"})
        _, export = self.request("GET", "/api/export")
        self.assertEqual(export["format"], "picture-postcard-manager")
        self.assertEqual(len(export["postcards"]), 2)

        status, result = self.request("POST", "/api/import?mode=append", export)
        self.assertEqual((status, result["imported"]), (200, 2))
        _, items = self.request("GET", "/api/postcards")
        self.assertEqual(len(items), 4)

        status, _ = self.request("POST", "/api/import?mode=replace", export)
        self.assertEqual(status, 200)
        _, items = self.request("GET", "/api/postcards")
        self.assertEqual(sorted(p["id"] for p in items), sorted(p["id"] for p in export["postcards"]))

    def test_invalid_import_is_rejected(self):
        status, body = self.request("POST", "/api/import", {"foo": 1})
        self.assertEqual(status, 400)
        status, _ = self.request("POST", "/api/import", raw=b"not json")
        self.assertEqual(status, 400)

    def test_static_files(self):
        with urllib.request.urlopen(self.base + "/") as res:
            self.assertIn(b"Picture Postcard Manager", res.read())
        status, _ = self.request("GET", "/../server.py")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
