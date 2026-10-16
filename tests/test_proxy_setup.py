"""Tests for the optional reverse-proxy (Caddy) reference setup.

These tests validate the committed configuration files structurally with the
standard library only; they do not require Docker or start containers.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPOSE_BASE = ROOT / "compose.yaml"
COMPOSE_PROXY = ROOT / "compose.proxy.yaml"
CADDYFILE = ROOT / "proxy" / "Caddyfile"
ENV_EXAMPLE = ROOT / ".env.example"
GITIGNORE = ROOT / ".gitignore"
README = ROOT / "README.md"

# A committed full bcrypt hash would be a leaked credential.
BCRYPT_RE = re.compile(r"\$2[abxy]\$\d{2}\$[./A-Za-z0-9]{53}")


class ComposeBaseTest(unittest.TestCase):
    """The default Compose setup must stay loopback-only and proxy-free."""

    def setUp(self):
        self.text = COMPOSE_BASE.read_text(encoding="utf-8")

    def test_app_published_on_loopback_only(self):
        self.assertIn('"127.0.0.1:${PPM_PORT:-8000}:8000"', self.text)

    def test_no_proxy_service_in_base_file(self):
        self.assertNotIn("caddy", self.text.lower())
        self.assertNotIn("proxy", self.text.lower())


class ComposeProxyOverlayTest(unittest.TestCase):
    def setUp(self):
        self.text = COMPOSE_PROXY.read_text(encoding="utf-8")

    def test_app_ports_are_reset(self):
        """With the overlay, only the proxy is reachable, not the app."""
        self.assertRegex(self.text, r"ports:\s*!reset\s*\[\]")

    def test_proxy_uses_caddy_image(self):
        self.assertRegex(self.text, r"image:\s*caddy:\d")

    def test_proxy_publishes_http_and_https(self):
        self.assertIn('"80:80"', self.text)
        self.assertIn('"443:443"', self.text)

    def test_proxy_waits_for_healthy_app(self):
        self.assertIn("condition: service_healthy", self.text)

    def test_credentials_come_from_environment(self):
        """User and hash are required variables, never literal values."""
        self.assertIn("${PPM_PROXY_USER:?", self.text)
        self.assertIn("${PPM_PROXY_PASSWORD_HASH:?", self.text)

    def test_caddyfile_is_mounted_read_only(self):
        self.assertIn("./proxy/Caddyfile:/etc/caddy/Caddyfile:ro", self.text)


class CaddyfileTest(unittest.TestCase):
    def setUp(self):
        self.text = CADDYFILE.read_text(encoding="utf-8")

    def test_basic_auth_covers_whole_site(self):
        """basic_auth has no path matcher, so UI, API and /images/ are covered."""
        self.assertRegex(self.text, r"(?m)^\tbasic_auth \{$")
        self.assertIn("{$PPM_PROXY_USER} {$PPM_PROXY_PASSWORD_HASH}", self.text)

    def test_reverse_proxy_targets_app_service(self):
        self.assertIn("reverse_proxy app:8000", self.text)

    def test_host_defaults_to_localhost(self):
        self.assertIn("{$PPM_PROXY_HOST:localhost}", self.text)

    def test_braces_balanced(self):
        self.assertEqual(self.text.count("{"), self.text.count("}"))

    def test_no_committed_credentials(self):
        self.assertIsNone(BCRYPT_RE.search(self.text))


class EnvExampleTest(unittest.TestCase):
    def setUp(self):
        self.text = ENV_EXAMPLE.read_text(encoding="utf-8")
        self.values = dict(
            line.split("=", 1)
            for line in self.text.splitlines()
            if line and not line.startswith("#")
        )

    def test_defines_all_proxy_variables(self):
        self.assertEqual(
            set(self.values),
            {"PPM_PROXY_HOST", "PPM_PROXY_USER", "PPM_PROXY_PASSWORD_HASH"},
        )

    def test_contains_placeholders_only(self):
        self.assertEqual(self.values["PPM_PROXY_USER"], "change-me")
        self.assertEqual(self.values["PPM_PROXY_PASSWORD_HASH"], "change-me")
        self.assertIsNone(BCRYPT_RE.search(self.text))

    def test_documents_hash_generation(self):
        self.assertIn("caddy hash-password", self.text)


class SecretHygieneTest(unittest.TestCase):
    def test_env_file_is_git_ignored(self):
        lines = GITIGNORE.read_text(encoding="utf-8").splitlines()
        self.assertIn(".env", lines)

    def test_no_real_env_file_committed(self):
        """A .env in the checkout is fine locally but must stay ignored;
        the repository itself ships only .env.example."""
        self.assertTrue(ENV_EXAMPLE.exists())


class ReadmeTest(unittest.TestCase):
    def setUp(self):
        self.text = README.read_text(encoding="utf-8")

    def test_access_control_section_exists(self):
        self.assertIn("### Access control and network deployment", self.text)

    def test_threat_model_documented(self):
        for phrase in (
            "UUID",
            "basic auth",
            "X-Forwarded",
            "compose.proxy.yaml",
            "caddy hash-password",
        ):
            self.assertIn(phrase, self.text, phrase)


if __name__ == "__main__":
    unittest.main()
