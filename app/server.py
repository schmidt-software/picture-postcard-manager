"""HTTP server: serves the web UI and a small JSON REST API.

Uses only the Python standard library.
"""

import json
import mimetypes
import os
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.db import Database

STATIC_DIR = Path(__file__).parent / "static"
MAX_BODY_BYTES = 50 * 1024 * 1024
ITEM_PATH = re.compile(r"^/api/postcards/(\d+)$")


class Handler(BaseHTTPRequestHandler):
    db: Database = None  # injected by make_server

    # --- helpers -----------------------------------------------------------

    def _send_json(self, status, data, extra_headers=None):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status, message):
        self._send_json(status, {"error": message})

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length < 0:
            raise ValueError("Content-Length must not be negative")
        if length > MAX_BODY_BYTES:
            raise ValueError("request body too large")
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(f"invalid JSON: {exc}") from exc

    def _serve_static(self, path):
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        file = (STATIC_DIR / rel).resolve()
        if not file.is_file() or STATIC_DIR.resolve() not in file.parents:
            return self._error(HTTPStatus.NOT_FOUND, "not found")
        body = file.read_bytes()
        ctype = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # --- routing -----------------------------------------------------------

    def do_GET(self):
        url = urlparse(self.path)
        params = parse_qs(url.query)
        if url.path == "/api/postcards":
            return self._send_json(HTTPStatus.OK, self.db.list(params.get("q", [None])[0]))
        if m := ITEM_PATH.match(url.path):
            item = self.db.get(int(m.group(1)))
            if item is None:
                return self._error(HTTPStatus.NOT_FOUND, "postcard not found")
            return self._send_json(HTTPStatus.OK, item)
        if url.path == "/api/export":
            return self._send_json(
                HTTPStatus.OK,
                self.db.export_data(),
                {"Content-Disposition": 'attachment; filename="postcards-export.json"'},
            )
        if url.path.startswith("/api/"):
            return self._error(HTTPStatus.NOT_FOUND, "unknown endpoint")
        return self._serve_static(url.path)

    def do_POST(self):
        url = urlparse(self.path)
        try:
            data = self._read_json()
            if url.path == "/api/postcards":
                if not isinstance(data, dict):
                    raise ValueError("postcard must be an object")
                return self._send_json(HTTPStatus.CREATED, self.db.create(data))
            if url.path == "/api/import":
                mode = parse_qs(url.query).get("mode", ["append"])[0]
                count = self.db.import_data(data, mode)
                return self._send_json(HTTPStatus.OK, {"imported": count, "mode": mode})
        except ValueError as exc:
            return self._error(HTTPStatus.BAD_REQUEST, str(exc))
        return self._error(HTTPStatus.NOT_FOUND, "unknown endpoint")

    def do_PUT(self):
        m = ITEM_PATH.match(urlparse(self.path).path)
        if not m:
            return self._error(HTTPStatus.NOT_FOUND, "unknown endpoint")
        try:
            data = self._read_json()
            if not isinstance(data, dict):
                raise ValueError("postcard must be an object")
            item = self.db.update(int(m.group(1)), data)
        except ValueError as exc:
            return self._error(HTTPStatus.BAD_REQUEST, str(exc))
        if item is None:
            return self._error(HTTPStatus.NOT_FOUND, "postcard not found")
        return self._send_json(HTTPStatus.OK, item)

    def do_DELETE(self):
        m = ITEM_PATH.match(urlparse(self.path).path)
        if not m:
            return self._error(HTTPStatus.NOT_FOUND, "unknown endpoint")
        if not self.db.delete(int(m.group(1))):
            return self._error(HTTPStatus.NOT_FOUND, "postcard not found")
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()


def make_server(host, port, db_path):
    db = Database(db_path)
    handler = type("BoundHandler", (Handler,), {"db": db})
    return ThreadingHTTPServer((host, port), handler)


def main():
    host = os.environ.get("PPM_HOST", "127.0.0.1")
    port = int(os.environ.get("PPM_PORT", "8000"))
    db_path = os.environ.get("PPM_DB_PATH", "data/postcards.db")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    server = make_server(host, port, db_path)
    print(f"Picture Postcard Manager running on http://{host}:{port} (db: {db_path})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
