"""Checks for the Mastodon release-announcement workflow.

Two layers, both dependency-free (no PyYAML, per the no-new-dependencies
convention):

1. Text-level security properties of ``.github/workflows/announce-release.yml``
   (triggers, permissions, guards, secret handling), mirroring the approach
   of ``tests/test_release_image.py``.
2. Behavioral tests of the embedded status-builder script: the Python code is
   extracted from the workflow's heredoc and executed in an isolated module
   namespace (its ``main()`` is guarded by ``__name__``), so the
   effective-length accounting, URL weighting and truncation logic are tested
   for real against Mastodon's 500-character limit.
"""

import re
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "announce-release.yml"

SECRET_NAME = "MASTODON_ACCESS_TOKEN"
SERVER = "https://kanoa.de"

RELEASE_URL = (
    "https://github.com/schmidt-software/picture-postcard-manager"
    "/releases/tag/v0.2.0"
)


def strip_comments(text):
    """Remove full-line and trailing YAML comments (naive, test-only)."""
    lines = []
    for line in text.splitlines():
        lines.append(re.sub(r"\s+#.*$", "", line))
    return "\n".join(line for line in lines if not line.lstrip().startswith("#"))


def extract_embedded_script(raw):
    """Return the dedented Python source embedded in the workflow heredoc."""
    match = re.search(r"python3 - <<'PY'\n(.*?)\n[ \t]*PY\n", raw, re.DOTALL)
    if match is None:
        raise AssertionError("workflow must embed the Python script")
    lines = match.group(1).splitlines()
    indent = min(len(l) - len(l.lstrip()) for l in lines if l.strip())
    return "\n".join(line[indent:] for line in lines)


def load_announce_module():
    """Execute the embedded script as a module (main() stays unexecuted)."""
    source = extract_embedded_script(WORKFLOW.read_text())
    module = types.ModuleType("announce_release_embedded")
    module.__name__ = "announce_release_embedded"  # not "__main__"
    exec(compile(source, "announce-release.yml <embedded>", "exec"),
         module.__dict__)
    return module


class AnnounceReleaseWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = WORKFLOW.read_text()
        cls.text = strip_comments(cls.raw)

    def test_workflow_exists(self):
        self.assertTrue(WORKFLOW.is_file())

    def test_triggers_only_on_release_published(self):
        on_block = re.search(
            r"^on:\n((?:[ \t]+.*\n|\n)*?)(?=^\S)", self.text, re.MULTILINE
        )
        self.assertIsNotNone(on_block, "workflow must have an on: block")
        body = on_block.group(1)
        self.assertIn("release:", body)
        self.assertRegex(body, r"types:\s*\[published\]")
        for forbidden in ("push:", "pull_request:", "workflow_dispatch:", "schedule:"):
            self.assertNotIn(forbidden, body, f"unexpected trigger {forbidden}")

    def test_no_repository_permissions(self):
        self.assertRegex(self.text, r"(?m)^permissions:\s*\{\}")

    def test_draft_and_prerelease_guard(self):
        guard = re.search(r"if:\s*\$\{\{(.+?)\}\}", self.text)
        self.assertIsNotNone(guard, "job must have an if: guard")
        condition = guard.group(1)
        self.assertIn("!github.event.release.draft", condition)
        self.assertIn("!github.event.release.prerelease", condition)

    def test_concurrency_group_per_release_tag(self):
        self.assertIn("concurrency:", self.text)
        self.assertIn("github.event.release.tag_name", self.text)
        self.assertRegex(self.text, r"cancel-in-progress:\s*false")

    def test_token_comes_from_named_secret_only(self):
        self.assertIn(f"secrets.{SECRET_NAME}", self.text)
        # GITHUB_TOKEN is never needed here.
        self.assertNotIn("secrets.GITHUB_TOKEN", self.text)

    def test_posts_to_kanoa_statuses_endpoint(self):
        self.assertIn(f"MASTODON_SERVER: {SERVER}", self.text)
        self.assertIn("/api/v1/statuses", self.raw)

    def test_release_metadata_passed_via_env_only(self):
        # Release name/notes are attacker-influenced; they must never be
        # interpolated into shell scripts.
        run_blocks = re.findall(r"run:\s*\|((?:\n[ \t]+.*)+)", self.raw)
        self.assertTrue(run_blocks, "workflow must have a run script")
        for block in run_blocks:
            self.assertNotIn(
                "${{", block, "no expression interpolation in run scripts"
            )
        for env_var in (
            "RELEASE_TAG", "RELEASE_NAME", "RELEASE_URL", "RELEASE_NOTES",
        ):
            self.assertRegex(
                self.text,
                rf"{env_var}:\s*\$\{{\{{ github\.event\.release\.",
                f"{env_var} must map a release field via env:",
            )

    def test_token_never_printed(self):
        # The embedded script must not echo or print the token; it may only
        # appear in os.environ reads and the Authorization header.
        body = extract_embedded_script(self.raw)
        for line in body.splitlines():
            if "print(" in line or "echo" in line:
                self.assertNotIn("token", line, "token must never be printed")

    def test_idempotency_key_prevents_duplicate_posts(self):
        self.assertIn("Idempotency-Key", self.raw)

    def test_basic_yaml_structure_is_sound(self):
        self.assertNotIn("\t", self.raw, "YAML indentation must not use tabs")
        top_keys = re.findall(r"^([A-Za-z_-]+):", self.text, re.MULTILINE)
        self.assertEqual(
            top_keys, ["name", "on", "concurrency", "permissions", "jobs"]
        )
        self.assertEqual(
            self.raw.count("${{"),
            len(re.findall(r"\$\{\{[^{}]*\}\}", self.raw)),
        )

    def test_embedded_python_script_compiles(self):
        source = extract_embedded_script(self.raw)
        compile(source, "announce-release.yml <embedded>", "exec")


class StatusBuilderTest(unittest.TestCase):
    """Behavioral tests of the embedded status-generation logic."""

    @classmethod
    def setUpClass(cls):
        cls.mod = load_announce_module()
        cls.LIMIT = cls.mod.STATUS_LIMIT
        cls.URL_WEIGHT = cls.mod.URL_WEIGHT

    # --- effective_length -------------------------------------------------

    def test_effective_length_plain_text(self):
        self.assertEqual(self.mod.effective_length("hello world"), 11)
        self.assertEqual(self.mod.effective_length(""), 0)

    def test_effective_length_weighs_every_url_as_23(self):
        short = "https://a.io"           # 12 real chars -> 23
        long = "https://example.com/" + "x" * 400  # huge -> 23
        self.assertEqual(self.mod.effective_length(short), 23)
        self.assertEqual(self.mod.effective_length(long), 23)
        text = f"see {short} and {long}!"
        self.assertEqual(
            self.mod.effective_length(text), 4 + 23 + 5 + 23 + 1
        )

    def test_effective_length_counts_urls_in_notes_style_text(self):
        notes = "Changelog: https://example.com/" + "y" * 600 + "\nDone."
        # 11 ("Changelog: ") + 23 (url) + 6 ("\nDone.")
        self.assertEqual(self.mod.effective_length(notes), 11 + 23 + 6)

    # --- truncate_to ------------------------------------------------------

    def test_truncate_noop_when_within_limit(self):
        self.assertEqual(self.mod.truncate_to("short", 10), "short")

    def test_truncate_appends_ellipsis_and_respects_limit(self):
        result = self.mod.truncate_to("a" * 600, 50)
        self.assertTrue(result.endswith("\u2026"))
        self.assertLessEqual(self.mod.effective_length(result), 50)

    def test_truncate_through_a_url_never_exceeds_limit(self):
        # Cutting inside a URL changes the weighting of the remainder from
        # 23 to its (possibly longer) literal prefix; the result must still
        # measure within the limit.
        text = "intro " + "https://example.com/" + "z" * 300
        for limit in (10, 23, 28, 29, 30, 40):
            result = self.mod.truncate_to(text, limit)
            self.assertLessEqual(
                self.mod.effective_length(result), limit,
                f"limit {limit} violated: {result!r}",
            )

    def test_truncate_is_deterministic(self):
        text = "x" * 1000
        self.assertEqual(
            self.mod.truncate_to(text, 100), self.mod.truncate_to(text, 100)
        )

    # --- build_status -----------------------------------------------------

    def build(self, tag="v0.2.0", name="v0.2.0", url=RELEASE_URL, notes=""):
        return self.mod.build_status(tag, name, url, notes)

    def test_minimal_release_no_notes(self):
        status = self.build(notes="")
        self.assertIn("Picture Postcard Manager v0.2.0 released", status)
        self.assertIn(RELEASE_URL, status)
        self.assertLessEqual(self.mod.effective_length(status), self.LIMIT)

    def test_name_and_tag_combined_when_distinct(self):
        status = self.build(name="Image pickers", tag="v0.2.0")
        self.assertIn("Image pickers (v0.2.0)", status)

    def test_short_notes_included_verbatim(self):
        status = self.build(notes="Adds image pickers and a version footer.")
        self.assertIn("Adds image pickers and a version footer.", status)
        self.assertLessEqual(self.mod.effective_length(status), self.LIMIT)

    def test_long_notes_truncated_url_survives(self):
        status = self.build(notes="w" * 2000)
        self.assertLessEqual(self.mod.effective_length(status), self.LIMIT)
        self.assertIn(RELEASE_URL, status)
        self.assertIn("\u2026", status)

    def test_notes_containing_long_urls_measured_by_weight(self):
        # Two very long URLs in the notes: literal length far above 500,
        # effective length far below, so the notes must survive untruncated.
        long_url = "https://example.com/release/" + "a" * 300
        notes = f"Details: {long_url}\nMirror: {long_url}"
        self.assertGreater(len(notes), self.LIMIT)
        status = self.build(notes=notes)
        self.assertIn(notes, status, "weighted-short notes must not be cut")
        self.assertLessEqual(self.mod.effective_length(status), self.LIMIT)

    def test_notes_with_many_short_urls_still_capped(self):
        # 40 short URLs weigh 40*23 = 920 effective chars; must be cut.
        notes = " ".join("https://e.io/%02d" % i for i in range(40))
        status = self.build(notes=notes)
        self.assertLessEqual(self.mod.effective_length(status), self.LIMIT)
        self.assertIn(RELEASE_URL, status)

    def test_extremely_long_release_name_is_truncated(self):
        status = self.build(name="N" * 800, tag="v0.2.0", notes="notes")
        self.assertLessEqual(self.mod.effective_length(status), self.LIMIT)
        self.assertIn(RELEASE_URL, status, "URL must survive a huge name")

    def test_extremely_long_tag_is_truncated(self):
        status = self.build(name="", tag="v1.0.0-" + "t" * 700)
        self.assertLessEqual(self.mod.effective_length(status), self.LIMIT)
        self.assertIn(RELEASE_URL, status)

    def test_no_url_at_all_still_capped(self):
        status = self.build(url="", notes="n" * 800)
        self.assertLessEqual(self.mod.effective_length(status), self.LIMIT)
        self.assertNotIn("https://", status)

    def test_exactly_at_limit_is_not_truncated(self):
        # Construct notes so the total effective length is exactly 500.
        headline = "Picture Postcard Manager v0.2.0 released"
        reserved = self.URL_WEIGHT + 2  # "\n\n" + weighted URL
        notes_budget = self.LIMIT - len(headline) - 2 - reserved
        notes = "n" * notes_budget
        status = self.build(notes=notes)
        self.assertEqual(self.mod.effective_length(status), self.LIMIT)
        self.assertIn(notes, status, "exact-fit notes must not be cut")
        self.assertNotIn("\u2026", status)

    def test_one_char_over_limit_is_truncated(self):
        headline = "Picture Postcard Manager v0.2.0 released"
        reserved = self.URL_WEIGHT + 2
        notes_budget = self.LIMIT - len(headline) - 2 - reserved
        status = self.build(notes="n" * (notes_budget + 1))
        self.assertLessEqual(self.mod.effective_length(status), self.LIMIT)
        self.assertIn("\u2026", status)
        self.assertIn(RELEASE_URL, status)

    def test_fuzz_never_exceeds_limit(self):
        cases = [
            dict(name="", tag="", url="", notes=""),
            dict(name="r" * 490, tag="v9.9.9", url=RELEASE_URL,
                 notes="https://x.io " * 100),
            dict(name="v1.0.0", tag="v1.0.0", url="https://e.io/" + "u" * 999,
                 notes="n" * 499),
            dict(name="\u00e4" * 600, tag="v0.1.0", url=RELEASE_URL,
                 notes="https://example.com/" + "p" * 480),
        ]
        for case in cases:
            status = self.mod.build_status(
                case["tag"], case["name"], case["url"], case["notes"]
            )
            self.assertLessEqual(
                self.mod.effective_length(status), self.LIMIT,
                f"limit violated for {case!r}",
            )


if __name__ == "__main__":
    unittest.main()
