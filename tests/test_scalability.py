"""Tests for pagination, per-thread database access and streamed image I/O."""

import http.client
import json
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from app.db import Database
from app.server import make_server

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


class PaginationDbTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        for index in range(1, 6):
            self.db.create({"front_image_path": f"/front-{index}.jpg",
                            "description": "Berlin" if index % 2 else "Munich"})

    def test_list_without_pagination_is_unchanged(self):
        items = self.db.list()
        self.assertEqual([p["id"] for p in items], [5, 4, 3, 2, 1])

    def test_limit_and_offset_page_through_newest_first(self):
        self.assertEqual([p["id"] for p in self.db.list(limit=2)], [5, 4])
        self.assertEqual([p["id"] for p in self.db.list(limit=2, offset=2)], [3, 2])
        self.assertEqual([p["id"] for p in self.db.list(limit=2, offset=4)], [1])
        self.assertEqual(self.db.list(limit=2, offset=5), [])
        self.assertEqual([p["id"] for p in self.db.list(offset=3)], [2, 1])

    def test_pagination_combines_with_search(self):
        self.assertEqual([p["id"] for p in self.db.list("Berlin", limit=2)], [5, 3])
        self.assertEqual([p["id"] for p in self.db.list("Berlin", limit=2, offset=2)], [1])

    def test_count(self):
        self.assertEqual(self.db.count(), 5)
        self.assertEqual(self.db.count("Berlin"), 3)
        self.assertEqual(self.db.count("missing"), 0)

    def test_invalid_pagination_is_rejected(self):
        for kwargs in ({"limit": 0}, {"limit": -1}, {"limit": "2"}, {"limit": True},
                       {"offset": -1}, {"offset": "3"}, {"offset": None}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    self.db.list(**kwargs)


class ConcurrencyTest(unittest.TestCase):
    def test_file_database_supports_concurrent_threads(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(str(Path(tmp) / "test.db"))
            self.addCleanup(db.close)
            errors = []

            def work(index):
                try:
                    created = db.create({"front_image_path": f"/front-{index}.jpg"})
                    db.get(created["id"])
                    db.list(limit=3)
                except Exception as exc:  # pragma: no cover - failure detail
                    errors.append(exc)

            threads = [threading.Thread(target=work, args=(i,)) for i in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(errors, [])
            self.assertEqual(db.count(), 8)

    def test_file_database_uses_wal_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.db"
            db = Database(str(path))
            self.addCleanup(db.close)
            self.assertEqual(
                db._conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")

    def test_closed_database_rejects_operations(self):
        db = Database(":memory:")
        db.close()
        with self.assertRaises(sqlite3.ProgrammingError):
            db.list()


class PaginationApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = make_server("127.0.0.1", 0, str(Path(self.tmp.name) / "test.db"))
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.db = self.server.RequestHandlerClass.db
        for index in range(1, 6):
            self.db.create({"front_image_path": f"/front-{index}.jpg"})

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.db.close()
        self.tmp.cleanup()

    def get(self, path):
        try:
            with urllib.request.urlopen(self.base + path) as res:
                return res.status, json.loads(res.read())
        except urllib.error.HTTPError as err:
            with err:
                return err.code, json.loads(err.read())

    def test_list_pagination(self):
        status, items = self.get("/api/postcards")
        self.assertEqual((status, len(items)), (200, 5))
        status, items = self.get("/api/postcards?limit=2")
        self.assertEqual((status, [p["id"] for p in items]), (200, [5, 4]))
        status, items = self.get("/api/postcards?limit=2&offset=4")
        self.assertEqual((status, [p["id"] for p in items]), (200, [1]))
        status, items = self.get("/api/postcards?offset=4")
        self.assertEqual((status, [p["id"] for p in items]), (200, [1]))

    def test_invalid_pagination_parameters(self):
        for query in ("limit=0", "limit=-1", "limit=x", "offset=-1", "offset=x",
                      "limit=2&offset=x"):
            with self.subTest(query=query):
                status, body = self.get(f"/api/postcards?{query}")
                self.assertEqual(status, 400)
                self.assertIn("error", body)

    def test_connections_are_released_after_requests(self):
        """Request threads must not leak SQLite connections (one per request).

        ThreadingHTTPServer serves each connection in a fresh thread; the
        handler releases the thread-local database connection when the
        request finishes, so the registry stays bounded regardless of how
        many requests were served.
        """
        baseline = self.db.open_connection_count()
        for _ in range(40):
            status, _items = self.get("/api/postcards?limit=1")
            self.assertEqual(status, 200)
        # Allow a small number of still-finishing handler threads.
        self.assertLessEqual(self.db.open_connection_count(), baseline + 2)

    def test_database_still_works_from_worker_threads(self):
        """After a release, the next operation on a thread reopens a connection."""
        errors = []

        def work(index):
            try:
                self.db.list(limit=1)
                self.db.release_thread_connection()
                created = self.db.create({"front_image_path": f"/thread-{index}.jpg"})
                self.assertIsNotNone(self.db.get(created["id"]))
                self.db.release_thread_connection()
            except Exception as exc:  # pragma: no cover - failure detail
                errors.append(exc)

        baseline = self.db.open_connection_count()
        threads = [threading.Thread(target=work, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(self.db.open_connection_count(), baseline)

    def test_streamed_image_upload_and_download(self):
        data = PNG + b"\x00" * (3 * 1024 * 1024)
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=30)
        try:
            conn.request("POST", "/api/images", body=data,
                         headers={"Content-Type": "image/png"})
            res = conn.getresponse()
            self.assertEqual(res.status, 201)
            result = json.loads(res.read())
            self.assertEqual(result["size"], len(data))
            conn.request("GET", result["path"])
            res = conn.getresponse()
            self.assertEqual(res.status, 200)
            self.assertEqual(res.read(), data)
        finally:
            conn.close()

    def test_incomplete_upload_is_rejected_without_partial_file(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=10)
        try:
            conn.putrequest("POST", "/api/images")
            conn.putheader("Content-Type", "image/png")
            conn.putheader("Content-Length", str(len(PNG) + 100))
            conn.endheaders()
            conn.send(PNG)
            conn.sock.shutdown(1)  # half-close: no more body bytes will arrive
            res = conn.getresponse()
            self.assertEqual(res.status, 400)
            self.assertIn("incomplete", json.loads(res.read())["error"])
        finally:
            conn.close()
        store = self.server.RequestHandlerClass.images.root
        files = list(store.glob("*")) if store.exists() else []
        self.assertEqual(files, [])


class PaginationUiTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is optional")
    def test_javascript_runtime(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [shutil.which("node"), str(root / "tests/pagination_runtime.js")],
            cwd=root, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
