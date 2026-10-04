import http.client
import json
import os
import re
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from app import images, server
from app.server import make_server

ROOT = Path(__file__).resolve().parents[1]
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32 + b"\xff\xd9"
GIF = b"GIF89a" + b"\x00" * 32
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 24
URL = re.compile(r"^/images/[0-9a-f]{32}\.(png|jpg|gif|webp)$")


class ImageApiTest(unittest.TestCase):
    image_dir = None

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "data" / "test.db"
        self.db_path.parent.mkdir()
        self.start(self.image_dir and self.root / self.image_dir)

    def start(self, image_dir=None):
        self.server = make_server("127.0.0.1", 0, str(self.db_path), image_dir)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.server.RequestHandlerClass.db.close()
        self.tmp.cleanup()

    @property
    def store_dir(self):
        return self.server.RequestHandlerClass.images.root

    def raw(self, method, path, body=None, headers=None, length=True):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.putrequest(method, path, skip_accept_encoding=True)
            for key, value in (headers or {}).items():
                conn.putheader(key, value)
            if length and body is not None:
                conn.putheader("Content-Length", str(len(body)))
            conn.endheaders()
            if body:
                try:
                    conn.send(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass
            res = conn.getresponse()
            return res.status, dict(res.getheaders()), res.read()
        finally:
            conn.close()

    def upload(self, data, ctype="image/png", headers=None):
        status, response_headers, body = self.raw(
            "POST", "/api/images", data, {"Content-Type": ctype, **(headers or {})})
        self.assertEqual(response_headers["Content-Type"], "application/json; charset=utf-8")
        return status, json.loads(body)

    def assertError(self, result, status, message):
        self.assertEqual(result, (status, {"error": message}))
        self.assertEqual(list(self.store_dir.glob("*")) if self.store_dir.exists() else [], [])


class UploadTest(ImageApiTest):
    def test_supported_formats_roundtrip(self):
        for data, ctype, ext in ((PNG, "image/png", "png"), (JPEG, "image/jpeg", "jpg"),
                                 (GIF, "image/gif", "gif"), (WEBP, "image/webp", "webp")):
            with self.subTest(ctype):
                status, result = self.upload(data, ctype + "; charset=binary")
                self.assertEqual(status, 201)
                self.assertRegex(result["path"], URL)
                self.assertTrue(result["path"].endswith("." + ext))
                self.assertEqual((result["content_type"], result["size"]), (ctype, len(data)))
                status, headers, body = self.raw("GET", result["path"])
                self.assertEqual((status, body), (200, data))
                self.assertEqual(headers["Content-Type"], ctype)
                self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
                self.assertIn("sandbox", headers["Content-Security-Policy"])

    def test_default_store_is_sibling_of_database(self):
        self.assertEqual(self.store_dir, (self.db_path.parent / "images").resolve())
        self.assertEqual(server.default_image_dir("/data/postcards.db"), Path("/data/images"))
        _, result = self.upload(PNG)
        stored = self.store_dir / result["path"].rsplit("/", 1)[1]
        self.assertEqual(stored.read_bytes(), PNG)

    def test_duplicate_uploads_never_overwrite(self):
        paths = {self.upload(PNG)[1]["path"] for _ in range(3)}
        self.assertEqual(len(paths), 3)
        self.assertEqual(len(list(self.store_dir.iterdir())), 3)
        name = next(iter(paths)).rsplit("/", 1)[1]
        with mock.patch("app.images.secrets.token_hex", side_effect=[name[:-4], "a" * 32]):
            status, result = self.upload(PNG)
        self.assertEqual((status, result["path"]), (201, f"/images/{'a' * 32}.png"))
        for path in paths:
            self.assertEqual(self.raw("GET", path)[2], PNG)

    def test_client_filenames_are_ignored(self):
        status, result = self.upload(PNG, headers={
            "X-Filename": "../../etc/passwd", "Content-Disposition": 'attachment; filename="../x.png"',
        })
        self.assertEqual(status, 201)
        self.assertRegex(result["path"], URL)
        self.assertEqual([p.parent for p in self.store_dir.iterdir()], [self.store_dir])

    def test_rejects_unsupported_and_invalid_content(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        cases = [
            (svg, "image/svg+xml", 415, images.ERROR_UNSUPPORTED_TYPE),
            (b"<html></html>", "text/html", 415, images.ERROR_UNSUPPORTED_TYPE),
            (PNG, "application/octet-stream", 415, images.ERROR_UNSUPPORTED_TYPE),
            (PNG, "", 415, images.ERROR_UNSUPPORTED_TYPE),
            (svg, "image/png", 415, images.ERROR_INVALID_CONTENT),
            (b"BM" + b"\x00" * 40, "image/png", 415, images.ERROR_INVALID_CONTENT),
            (PNG, "image/jpeg", 415, images.ERROR_INVALID_CONTENT),
            (b"RIFF\x00\x00\x00\x00WAVE", "image/webp", 415, images.ERROR_INVALID_CONTENT),
            (b"", "image/png", 400, images.ERROR_EMPTY),
        ]
        for data, ctype, status, message in cases:
            with self.subTest(ctype=ctype, data=data[:8]):
                self.assertError(self.upload(data, ctype), status, message)

    def test_size_limit(self):
        self.assertEqual(images.MAX_IMAGE_BYTES, 20 * 1024 * 1024)
        status, _, body = self.raw("POST", "/api/images", None, {
            "Content-Type": "image/png", "Content-Length": str(images.MAX_IMAGE_BYTES + 1),
        })
        self.assertError((status, json.loads(body)), 413, images.ERROR_TOO_LARGE)
        data = PNG + b"\x00" * (images.MAX_IMAGE_BYTES - len(PNG))
        status, result = self.upload(data)
        self.assertEqual((status, result["size"]), (201, images.MAX_IMAGE_BYTES))
        source = (ROOT / "app" / "static" / "app.js").read_text()
        self.assertIn("const MAX_IMAGE_BYTES = 20 * 1024 * 1024;", source)

    def test_missing_or_invalid_length(self):
        status, _, body = self.raw("POST", "/api/images", None, {"Content-Type": "image/png"})
        self.assertEqual((status, json.loads(body)),
                         (411, {"error": "Content-Length header is required"}))
        status, _, body = self.raw("POST", "/api/images", None,
                                   {"Content-Type": "image/png", "Content-Length": "-1"})
        self.assertEqual(status, 400)

    def test_storage_failure_returns_500_without_paths(self):
        self.store_dir.parent.mkdir(parents=True, exist_ok=True)
        self.store_dir.write_bytes(b"not a directory")
        with mock.patch.object(server.Handler, "log_error") as log:
            status, headers, body = self.raw(
                "POST", "/api/images", PNG, {"Content-Type": "image/png"})
        self.assertEqual((status, json.loads(body)), (500, {"error": images.ERROR_STORAGE}))
        self.assertNotIn(self.tmp.name.encode(), body)
        log.assert_called_once()
        self.assertIn("image storage failed", log.call_args[0][0])

    def test_write_failure_removes_partial_file(self):
        with mock.patch("app.images.os.fsync", side_effect=OSError("disk full")), \
                mock.patch.object(server.Handler, "log_error"):
            status, result = self.upload(PNG)
        self.assertEqual((status, result), (500, {"error": images.ERROR_STORAGE}))
        self.assertEqual(list(self.store_dir.iterdir()), [])

    def test_uploaded_path_is_saved_and_exported(self):
        _, front = self.upload(PNG)
        _, back = self.upload(JPEG, "image/jpeg")
        card = {"front_image_path": front["path"], "back_image_path": back["path"]}
        status, _, body = self.raw("POST", "/api/postcards", json.dumps(card).encode(),
                                   {"Content-Type": "application/json"})
        self.assertEqual(status, 201)
        _, _, body = self.raw("GET", "/api/export")
        exported = json.loads(body)["postcards"][0]
        self.assertEqual((exported["front_image_path"], exported["back_image_path"]),
                         (front["path"], back["path"]))
        self.assertNotIn(b"\x89PNG", body)


class ServeTest(ImageApiTest):
    def assertNotServed(self, path):
        status, headers, body = self.raw("GET", path)
        self.assertEqual(status, 404, path)
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        return body

    def test_only_generated_image_names_are_served(self):
        _, result = self.upload(PNG)
        name = result["path"].rsplit("/", 1)[1]
        (self.db_path.parent / "secret.png").write_bytes(PNG)
        for path in (
            "/images/", "/images/../test.db", "/images/..%2ftest.db", "/images/%2e%2e%2ftest.db",
            "/images/%2E%2E/secret.png", "/images/..%5csecret.png", "/images/../secret.png",
            "/images//etc/passwd", "/images/" + name.upper(), "/images/" + name + "/",
            "/images/%2f" + name, "/images/" + name.replace(".png", "%2epng"),
            "/images/" + name + "%00", "/images/" + "0" * 32 + ".png",
            "/images/" + "0" * 32 + ".svg", "/images/sub/" + name,
        ):
            with self.subTest(path):
                self.assertNotServed(path)
        self.assertEqual(self.raw("GET", result["path"] + "?v=1")[0], 200)

    def test_symlinks_and_untrusted_files_are_not_served(self):
        self.upload(PNG)
        outside = self.db_path.parent / "outside.png"
        outside.write_bytes(PNG)
        os.symlink(outside, self.store_dir / ("1" * 32 + ".png"))
        os.symlink(self.store_dir, self.store_dir / ("4" * 32 + ".png"))
        (self.store_dir / ("2" * 32 + ".png")).write_bytes(b"<html><script></script></html>")
        (self.store_dir / ("3" * 32 + ".gif")).write_bytes(PNG)
        (self.store_dir / ("5" * 32 + ".png")).mkdir()
        cases = [("1", "png"), ("2", "png"), ("3", "gif"), ("4", "png"), ("5", "png")]
        if hasattr(os, "mkfifo"):
            os.mkfifo(self.store_dir / ("6" * 32 + ".png"))
            cases.append(("6", "png"))
        for digit, ext in cases:
            with self.subTest(digit):
                body = self.assertNotServed(f"/images/{digit * 32}.{ext}")
                self.assertEqual(json.loads(body), {"error": images.ERROR_NOT_FOUND})

    def test_static_files_still_served(self):
        self.assertEqual(self.raw("GET", "/")[0], 200)
        self.assertEqual(self.raw("GET", "/app.js")[0], 200)


class ConfiguredDirectoryTest(ImageApiTest):
    image_dir = "custom/store"

    def test_configured_directory_is_used(self):
        self.assertEqual(self.store_dir, (self.root / "custom" / "store").resolve())
        status, result = self.upload(GIF, "image/gif")
        self.assertEqual(status, 201)
        self.assertTrue((self.store_dir / result["path"].rsplit("/", 1)[1]).is_file())
        self.assertFalse((self.db_path.parent / "images").exists())

    def test_environment_variable_configures_main(self):
        captured = {}

        class FakeServer:
            def serve_forever(self):
                raise KeyboardInterrupt

            def server_close(self):
                pass

        def fake_make_server(host, port, db_path, image_dir):
            captured.update(db_path=db_path, image_dir=image_dir)
            return FakeServer()

        image_dir = str(self.root / "startup-images")
        env = {"PPM_DB_PATH": str(self.db_path), "PPM_IMAGE_DIR": image_dir}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(server, "make_server", fake_make_server), \
                mock.patch("builtins.print"):
            server.main()
        self.assertEqual(captured["image_dir"], image_dir)
        self.assertTrue(Path(image_dir).is_dir())
        with mock.patch.dict(os.environ, {"PPM_DB_PATH": str(self.db_path)}), \
                mock.patch.dict(os.environ, {"PPM_IMAGE_DIR": ""}), \
                mock.patch.object(server, "make_server", fake_make_server), \
                mock.patch("builtins.print"):
            server.main()
        self.assertEqual(captured["image_dir"], self.db_path.parent / "images")


if __name__ == "__main__":
    unittest.main()
