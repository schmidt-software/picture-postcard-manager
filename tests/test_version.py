"""Tests for the application version source and endpoint (issue #44).

The ``PPM_VERSION`` environment variable is the single authoritative runtime
source of the public version string; ``GET /api/version`` exposes it to the
frontend footer. These tests cover the default fallback, configured values,
validation of blank/overlong/non-printable input, safe JSON encoding of
hostile payloads, and the cache semantics that keep the footer fresh across
deploys.
"""

import json
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from app.server import MAX_VERSION_LENGTH, VERSION_FALLBACK, app_version, make_server

ROOT = Path(__file__).resolve().parents[1]


class AppVersionTest(unittest.TestCase):
    def set_version(self, value):
        if value is None:
            patcher = mock.patch.dict("os.environ", clear=False)
            env = patcher.start()
            self.addCleanup(patcher.stop)
            env.pop("PPM_VERSION", None)
        else:
            patcher = mock.patch.dict("os.environ", {"PPM_VERSION": value})
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_unset_falls_back_to_dev(self):
        self.set_version(None)
        self.assertEqual(app_version(), VERSION_FALLBACK)
        self.assertEqual(VERSION_FALLBACK, "dev")

    def test_configured_version_is_returned(self):
        self.set_version("0.1.0")
        self.assertEqual(app_version(), "0.1.0")

    def test_prerelease_version_is_returned(self):
        self.set_version("1.2.3-rc.1")
        self.assertEqual(app_version(), "1.2.3-rc.1")

    def test_surrounding_whitespace_is_stripped(self):
        self.set_version("  0.1.0\n")
        self.assertEqual(app_version(), "0.1.0")

    def test_blank_value_falls_back(self):
        for value in ("", "   ", "\t\n"):
            with self.subTest(value=value):
                self.set_version(value)
                self.assertEqual(app_version(), VERSION_FALLBACK)

    def test_overlong_value_falls_back(self):
        self.set_version("x" * (MAX_VERSION_LENGTH + 1))
        self.assertEqual(app_version(), VERSION_FALLBACK)
        self.set_version("x" * MAX_VERSION_LENGTH)
        self.assertEqual(app_version(), "x" * MAX_VERSION_LENGTH)

    def test_non_printable_value_falls_back(self):
        # A real environment cannot hold a null byte, so patch the mapping
        # that app_version reads instead of the process environment.
        for value in ("0.1\x000", "0.1\x1b[31m0", "a\nb"):
            with self.subTest(value=value):
                with mock.patch("app.server.os.environ", {"PPM_VERSION": value}):
                    self.assertEqual(app_version(), VERSION_FALLBACK)


class VersionEndpointTest(unittest.TestCase):
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

    def request(self):
        import urllib.request

        with urllib.request.urlopen(self.base + "/api/version") as res:
            return res.status, dict(res.headers), json.loads(res.read())

    def test_default_version_is_dev(self):
        with mock.patch.dict("os.environ", clear=False) as env:
            env.pop("PPM_VERSION", None)
            status, headers, body = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(body, {"version": "dev"})

    def test_configured_version_is_served(self):
        with mock.patch.dict("os.environ", {"PPM_VERSION": "0.1.0"}):
            status, _, body = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(body, {"version": "0.1.0"})

    def test_response_is_json_and_must_be_revalidated(self):
        """no-cache keeps the footer fresh across deploys without disabling caching."""
        with mock.patch.dict("os.environ", {"PPM_VERSION": "0.1.0"}):
            _, headers, _ = self.request()
        self.assertEqual(headers.get("Cache-Control"), "no-cache")
        self.assertTrue(headers.get("Content-Type", "").startswith("application/json"))

    def test_hostile_payload_is_json_encoded_data_only(self):
        """A markup payload stays an inert JSON string (never HTML)."""
        payload = "<script>alert(1)</script><img src=x onerror=alert(1)>"
        with mock.patch.dict("os.environ", {"PPM_VERSION": payload}):
            _, headers, body = self.request()
        self.assertEqual(body, {"version": payload})
        self.assertTrue(headers.get("Content-Type", "").startswith("application/json"))

    def test_no_operational_details_are_exposed(self):
        with mock.patch.dict("os.environ", {"PPM_VERSION": "0.1.0"}):
            _, _, body = self.request()
        self.assertEqual(set(body), {"version"})

    @unittest.skipUnless(shutil.which("node"), "Node.js is optional")
    def test_footer_runtime(self):
        result = subprocess.run(
            [shutil.which("node"), str(ROOT / "tests" / "footer_runtime.js")],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class VersionWiringTest(unittest.TestCase):
    """Docker-free checks: images and Compose supply PPM_VERSION correctly."""

    def test_dockerfile_defaults_version_to_dev(self):
        text = (ROOT / "Dockerfile").read_text()
        self.assertRegex(text, r"(?m)^ARG PPM_VERSION=dev$",
                         "untagged image builds must default to dev")
        self.assertRegex(text, r"PPM_VERSION=\$PPM_VERSION",
                         "the build arg must be exposed as a runtime ENV")

    def test_compose_passes_version_build_arg_with_dev_default(self):
        text = (ROOT / "compose.yaml").read_text()
        self.assertRegex(text, r"PPM_VERSION:\s*\$\{PPM_VERSION:-dev\}",
                         "Compose must default the version to dev and allow overrides")

    def test_release_workflow_bakes_release_version_into_image(self):
        """The publish job derives X.Y.Z from the tag and passes it to the build.

        This proves the wiring for future releases; already-published images
        (e.g. v0.1.0) are immutable and are not rebuilt retroactively.
        """
        text = (ROOT / ".github" / "workflows" / "release-image.yml").read_text()
        # The version is derived by stripping the v prefix from the validated
        # tag, with the tag passed via env: (never interpolated into run:).
        derive = re.search(
            r"id: app_version\n\s+env:\n\s+TAG: \$\{\{ github\.event\.release\.tag_name \}\}"
            r"\n\s+run: \|\n\s+echo \"version=\$\{TAG#v\}\"",
            text,
        )
        self.assertIsNotNone(derive, "workflow must derive the version from the release tag")
        # The derived version reaches the Docker build as the PPM_VERSION arg.
        self.assertRegex(
            text,
            r"build-args: \|\n\s+PPM_VERSION=\$\{\{ steps\.app_version\.outputs\.version \}\}",
            "the build step must pass the derived version as a build argument",
        )
        # The version derivation runs after semver validation (validation is
        # the first step), so only valid semver ever reaches the image.
        self.assertLess(text.index("Validate release tag is strict semver"),
                        text.index("id: app_version"))

    def test_release_workflow_still_builds_the_exact_tag(self):
        """Regression guard: version wiring must not change the checkout."""
        text = (ROOT / ".github" / "workflows" / "release-image.yml").read_text()
        self.assertRegex(text, r"ref: \$\{\{ github\.event\.release\.tag_name \}\}")

    def test_footer_styles_cover_narrow_screens_and_forced_colors(self):
        css = (ROOT / "app" / "static" / "style.css").read_text()
        self.assertIn("footer", css)
        self.assertRegex(css, r"@media \(forced-colors: active\)\s*\{[^}]*footer",
                         "the footer needs a forced-colors rule")
        narrow = re.search(r"@media \(max-width: 480px\)\s*\{[^@]*footer", css, re.S)
        self.assertIsNotNone(narrow, "the footer needs a narrow-screen rule")

    def test_no_hardcoded_version_in_frontend(self):
        """The frontend must not duplicate a version independently of the API."""
        static = ROOT / "app" / "static"
        for file in [static / "index.html", static / "app.js", static / "languages.js",
                     *sorted((static / "js").glob("*.js"))]:
            self.assertNotRegex(
                file.read_text(), r"\b\d+\.\d+\.\d+\b",
                f"{file.name} must not hard-code a version number",
            )


if __name__ == "__main__":
    unittest.main()
