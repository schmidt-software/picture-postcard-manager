"""Docker-free checks for the GHCR release-image workflow and its docs.

The tests parse ``.github/workflows/release-image.yml`` as text (no PyYAML,
per the no-new-dependencies convention) and assert the security-relevant
properties promised in issue #42: publish only on published releases, with a
least-privilege token, for both platforms, from the exact release tag, with
semver validation and a stable-only ``latest`` tag.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release-image.yml"
README = ROOT / "README.md"

TAG_PATTERN = (
    r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(-[0-9A-Za-z]+(\.[0-9A-Za-z]+)*)?$"
)


def strip_comments(text):
    """Remove full-line and trailing YAML comments (naive, test-only)."""
    lines = []
    for line in text.splitlines():
        # Good enough here: the workflow has no '#' inside quoted strings.
        lines.append(re.sub(r"\s+#.*$", "", line))
    return "\n".join(line for line in lines if not line.lstrip().startswith("#"))


class ReleaseImageWorkflowTest(unittest.TestCase):
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

    def test_permissions_are_least_privilege(self):
        perms = re.search(
            r"^permissions:\n((?:[ \t]+\S.*\n)+)", self.text, re.MULTILINE
        )
        self.assertIsNotNone(perms, "workflow must set explicit permissions")
        entries = dict(
            re.findall(r"^[ \t]+([a-z-]+):\s*(\S+)", perms.group(1), re.MULTILINE)
        )
        self.assertEqual(
            entries, {"contents": "read", "packages": "write"},
            "token must be exactly contents: read + packages: write",
        )

    def test_concurrency_group_per_release_tag(self):
        self.assertIn("concurrency:", self.text)
        self.assertIn("github.event.release.tag_name", self.text)
        self.assertRegex(self.text, r"cancel-in-progress:\s*false")

    def test_publishes_to_ghcr_repository_path(self):
        self.assertIn("ghcr.io/${{ github.repository }}", self.text)
        self.assertRegex(self.text, r"registry:\s*ghcr\.io")

    def test_semver_validation_guards_publication(self):
        # A grep -E guard on the tag, exported through env (no direct shell
        # interpolation of the attacker-influenced tag name).
        self.assertRegex(self.raw, r"grep -Eq '[^']*\^v\(0\|\[1-9\]")
        self.assertRegex(self.raw, r"TAG:\s*\$\{\{ github\.event\.release\.tag_name \}\}")
        # The regex in the workflow matches the convention we document.
        match = re.search(r"grep -Eq '([^']+)'", self.raw)
        self.assertIsNotNone(match)
        pattern = match.group(1).rstrip("\n").replace("\\n", "")
        pattern = pattern.strip()
        for good in ("v0.1.0", "v1.2.3", "v10.20.30", "v1.0.0-rc.1"):
            self.assertRegex(good, pattern, f"{good} must be accepted")
        for bad in ("0.1.0", "v1.2", "v01.2.3", "release-1", "v1.2.3 evil", "latest"):
            self.assertNotRegex(bad, pattern, f"{bad} must be rejected")

    def test_checkout_uses_release_tag_ref(self):
        checkout = re.search(
            r"uses:\s*actions/checkout@\S+\n(?:.*\n)*?[ \t]+ref:\s*(\S.*)",
            self.text,
        )
        self.assertIsNotNone(checkout, "checkout must pin an explicit ref")
        self.assertIn("github.event.release.tag_name", checkout.group(1))

    def test_ancestry_check_against_main(self):
        self.assertIn("merge-base --is-ancestor", self.raw)
        self.assertIn("origin/main", self.raw)

    def test_platforms_amd64_and_arm64(self):
        platforms = re.search(r"platforms:\s*(\S+)", self.text)
        self.assertIsNotNone(platforms)
        values = set(platforms.group(1).split(","))
        self.assertEqual(values, {"linux/amd64", "linux/arm64"})

    def test_login_and_push_with_github_token(self):
        self.assertIn("docker/login-action@", self.text)
        self.assertIn("secrets.GITHUB_TOKEN", self.text)
        self.assertRegex(self.text, r"push:\s*true")

    def test_latest_only_for_stable_releases(self):
        # metadata-action's implicit latest is disabled; the explicit latest
        # tag is gated on the release not being a prerelease.
        self.assertRegex(self.text, r"latest=false")
        self.assertRegex(
            self.text,
            r"type=raw,value=latest,enable=\$\{\{ !github\.event\.release\.prerelease \}\}",
        )

    def test_draft_guard_present(self):
        self.assertRegex(self.text, r"if:.*!github\.event\.release\.draft")

    def test_oci_labels_use_release_commit_and_tag(self):
        self.assertIn("org.opencontainers.image.revision=", self.text)
        self.assertIn("org.opencontainers.image.version=", self.text)
        self.assertIn("org.opencontainers.image.source=", self.text)
        self.assertIn(
            "steps.release_commit.outputs.release_commit", self.text,
            "revision label must use the actually checked-out commit",
        )

    def test_all_actions_pinned_to_commit_shas(self):
        uses = re.findall(r"uses:\s*(\S+)", self.raw)
        self.assertTrue(uses, "workflow must use actions")
        for ref in uses:
            name, _, pin = ref.partition("@")
            self.assertRegex(
                pin, r"^[0-9a-f]{40}$",
                f"{name} must be pinned to a 40-char commit SHA, got '{pin}'",
            )

    def test_no_unescaped_release_metadata_in_run_scripts(self):
        # Release name/body are attacker-influenced; they must never be
        # interpolated into shell scripts (tag_name is passed via env only).
        run_blocks = re.findall(
            r"run:\s*\|((?:\n[ \t]+.*)+)", self.raw
        )
        for block in run_blocks:
            self.assertNotIn("${{", block, "no expression interpolation in run scripts")

    def test_supply_chain_attestations_enabled(self):
        self.assertRegex(self.text, r"provenance:\s*mode=max")
        self.assertRegex(self.text, r"sbom:\s*true")

    def test_basic_yaml_structure_is_sound(self):
        # Minimal structural sanity without a YAML dependency: consistent
        # top-level keys, no tabs (YAML forbids tabs for indentation), and
        # balanced ${{ }} expressions.
        self.assertNotIn("\t", self.raw, "YAML indentation must not use tabs")
        top_keys = re.findall(r"^([A-Za-z_-]+):", self.text, re.MULTILINE)
        self.assertEqual(
            top_keys, ["name", "on", "concurrency", "permissions", "jobs"]
        )
        # Every ${{ expression closes (bare {{version}} in metadata-action
        # patterns is not an expression and is excluded).
        self.assertEqual(
            self.raw.count("${{"),
            len(re.findall(r"\$\{\{[^{}]*\}\}", self.raw)),
        )


class ReleaseImageDocsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme = README.read_text()

    def test_documents_pull_command(self):
        self.assertIn(
            "docker pull ghcr.io/schmidt-software/picture-postcard-manager:0.1.0",
            self.readme,
        )

    def test_documents_run_with_volume_and_loopback_port(self):
        run_cmd = re.search(
            r"docker run[^`]*ghcr\.io/schmidt-software/picture-postcard-manager:0\.1\.0",
            self.readme,
            re.DOTALL,
        )
        self.assertIsNotNone(run_cmd, "README must show a docker run example")
        block = run_cmd.group(0)
        self.assertIn("-v postcard-data:/data", block)
        self.assertIn("-p 127.0.0.1:8000:8000", block)

    def test_documents_tag_convention(self):
        for needle in ("`latest`", "Prerelease", "v0.1.0"):
            self.assertIn(needle, self.readme)
        self.assertIn("never", self.readme.split("## Container images")[1][:2000])

    def test_documents_non_root_and_visibility_caveat(self):
        section = self.readme.split("## Container images")[1].split("\n## ")[0]
        self.assertIn("ppm", section)
        self.assertIn("visibility", section)


if __name__ == "__main__":
    unittest.main()
