"""Tests for the lightweight health endpoint used by the Docker healthcheck."""

import json
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from app.server import make_server


class HealthTest(unittest.TestCase):
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

    def request(self, path):
        try:
            with urllib.request.urlopen(self.base + path) as res:
                return res.status, json.loads(res.read())
        except urllib.error.HTTPError as err:
            with err:
                return err.code, json.loads(err.read())

    def test_health_ok(self):
        status, body = self.request("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"status": "ok"})

    def test_health_fails_when_database_is_unavailable(self):
        self.server.RequestHandlerClass.db.close()
        status, body = self.request("/api/health")
        self.assertEqual(status, 503)
        self.assertEqual(body["status"], "error")
        self.assertIn("error", body)

    def test_compose_healthcheck_uses_health_endpoint(self):
        compose = (Path(__file__).resolve().parents[1] / "compose.yaml").read_text()
        match = re.search(r"test:.*urlopen\('([^']+)'", compose)
        self.assertIsNotNone(match)
        self.assertTrue(match.group(1).endswith("/api/health"))


if __name__ == "__main__":
    unittest.main()
