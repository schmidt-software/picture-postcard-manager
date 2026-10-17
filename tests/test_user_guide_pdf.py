"""Docker-free checks for the user-guide PDF pipeline (Refs #49).

Like ``tests/test_release_image.py``, these parse the workflow YAML as text
(no PyYAML, per the no-new-dependencies convention) and assert the
security-relevant properties promised in issue #49: strict tag validation,
exact-tag checkout and source selection, least-privilege permissions,
SHA-pinned actions, deterministic dates, duplicate-safe uploads, and a
manual backfill path. They also check the build/validate scripts and the
retrospective v0.1.0 snapshot guide without running Docker.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release-user-guide.yml"
PR_WORKFLOW = ROOT / ".github" / "workflows" / "docs-pdf.yml"
IMAGE_WORKFLOW = ROOT / ".github" / "workflows" / "release-image.yml"
BUILD_SCRIPT = ROOT / "tools" / "pdf" / "build_pdf.py"
VALIDATE_SCRIPT = ROOT / "tools" / "pdf" / "validate_pdf.py"
VALIDATE_REQUIREMENTS = ROOT / "tools" / "pdf" / "requirements-validate.txt"
SNAPSHOT = ROOT / "docs" / "releases" / "v0.1.0" / "user-guide.md"
GUIDE = ROOT / "docs" / "user-guide.md"

TAG_PATTERN = (
    r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(-[0-9A-Za-z]+(\.[0-9A-Za-z]+)*)?$"
)
ASSET_PREFIX = "picture-postcard-manager-user-guide-"


def strip_comments(text):
    """Remove full-line and trailing YAML comments (naive, test-only)."""
    lines = []
    for line in text.splitlines():
        lines.append(re.sub(r"\s+#.*$", "", line))
    return "\n".join(line for line in lines if not line.lstrip().startswith("#"))


class ReleaseGuideWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = RELEASE_WORKFLOW.read_text()
        cls.text = strip_comments(cls.raw)

    def test_workflow_exists(self):
        self.assertTrue(RELEASE_WORKFLOW.is_file())

    def test_triggers_release_published_and_manual_backfill_only(self):
        on_block = re.search(
            r"^on:\n((?:[ \t]+.*\n|\n)*?)(?=^\S)", self.text, re.MULTILINE
        )
        self.assertIsNotNone(on_block, "workflow must have an on: block")
        body = on_block.group(1)
        self.assertIn("release:", body)
        self.assertRegex(body, r"types:\s*\[published\]")
        self.assertIn("workflow_dispatch:", body)
        for forbidden in ("push:", "pull_request:", "schedule:"):
            self.assertNotIn(forbidden, body, f"unexpected trigger {forbidden}")

    def test_default_permissions_are_read_only(self):
        default = re.search(
            r"^permissions:\n((?:[ \t]+\S.*\n)+)", self.text, re.MULTILINE
        )
        self.assertIsNotNone(default, "workflow must set explicit permissions")
        entries = dict(
            re.findall(r"^[ \t]+([a-z-]+):\s*(\S+)", default.group(1), re.MULTILINE)
        )
        self.assertEqual(entries, {"contents": "read"})

    def test_only_the_upload_job_gets_contents_write(self):
        job_permissions = re.findall(
            r"^[ \t]+permissions:\n((?:[ \t]{4,}[a-z-]+:.*\n)+)",
            self.text,
            re.MULTILINE,
        )
        writes = [block for block in job_permissions if "contents: write" in block]
        self.assertEqual(len(writes), 1, "exactly one job may hold contents: write")
        upload_job = self.text[self.text.index("  upload:"):]
        self.assertIn("contents: write", upload_job)
        build_job = self.text[
            self.text.index("  build:"):self.text.index("  upload:")
        ]
        self.assertNotIn("contents: write", build_job)
        self.assertNotIn("packages:", self.text)

    def test_no_long_lived_secret(self):
        secrets = set(re.findall(r"secrets\.([A-Za-z_0-9]+)", self.raw))
        self.assertEqual(secrets, {"GITHUB_TOKEN"})

    def test_all_actions_are_sha_pinned(self):
        for match in re.finditer(r"uses:\s*(\S+)", self.text):
            reference = match.group(1)
            name, _, ref = reference.partition("@")
            self.assertRegex(
                ref, r"^[0-9a-f]{40}$", f"action {name} must be pinned by commit SHA"
            )

    def test_tag_validation_matches_release_image_workflow(self):
        pattern = re.search(r"grep -Eq '([^']+)'", self.raw)
        self.assertIsNotNone(pattern, "workflow must grep-validate the tag")
        image = IMAGE_WORKFLOW.read_text()
        self.assertIn(
            pattern.group(1), image,
            "tag pattern must match release-image.yml",
        )

    def test_tag_used_only_via_env(self):
        # The tag may appear in expressions (env:, with:, concurrency), but
        # never interpolated into a run: script line.
        in_run = False
        for line in self.raw.splitlines():
            stripped = line.strip()
            if stripped.startswith("run:"):
                in_run = True
                continue
            if in_run and (stripped.startswith("- name:") or stripped.startswith("- uses:")):
                in_run = False
            if in_run:
                self.assertNotIn(
                    "${{", line, f"no expression interpolation inside run: {line!r}"
                )

    def test_exact_tag_checkout_and_ancestry_check(self):
        self.assertRegex(
            self.text, r"ref:\s*\$\{\{ steps\.tag\.outputs\.tag \}\}"
        )
        self.assertIn("fetch-depth: 0", self.text)
        self.assertIn("merge-base --is-ancestor", self.text)
        self.assertIn("origin/main", self.text)

    def test_source_selection_exact_tag_then_v010_snapshot_only(self):
        selection = self.text[self.text.index("Select the guide source"):]
        selection = selection[:selection.index("Derive")]
        tag_index = selection.index("release-src/docs/user-guide.md")
        snapshot_index = selection.index("docs/releases/v0.1.0/user-guide.md")
        self.assertLess(
            tag_index, snapshot_index,
            "exact-tag documentation must be preferred over the snapshot",
        )
        # The snapshot fallback is hard-coded to the literal tag v0.1.0; no
        # generic docs/releases/$TAG path may exist anywhere in the workflow.
        self.assertIn('"$TAG" = "v0.1.0"', selection)
        self.assertNotIn("docs/releases/$TAG", self.text)
        self.assertNotIn("docs/releases/${TAG}", self.text)
        self.assertIn("exit 1", selection)

    @staticmethod
    def _selection_script():
        """Extract the source-selection shell script from the workflow."""
        raw = RELEASE_WORKFLOW.read_text()
        step = raw[raw.index("Select the guide source"):]
        run = step[step.index("run: |") + len("run: |"):]
        lines = []
        for line in run.splitlines()[1:]:
            if line.strip() and not line.startswith(" " * 10):
                break
            lines.append(line[10:] if len(line) > 10 else "")
        return "\n".join(lines)

    def _run_selection(self, tag, exact_guide, snapshot):
        """Run the real selection script against a synthetic tree."""
        import os
        import subprocess
        import tempfile

        script = self._selection_script()
        with tempfile.TemporaryDirectory() as tmp:
            if exact_guide:
                os.makedirs(os.path.join(tmp, "release-src", "docs"))
                Path(tmp, "release-src", "docs", "user-guide.md").write_text("x")
            if snapshot:
                os.makedirs(os.path.join(tmp, "docs", "releases", "v0.1.0"))
                Path(
                    tmp, "docs", "releases", "v0.1.0", "user-guide.md"
                ).write_text("x")
            out = Path(tmp, "out")
            out.write_text("")
            env = dict(os.environ, TAG=tag, GITHUB_OUTPUT=str(out))
            proc = subprocess.run(
                ["bash", "-euo", "pipefail", "-c", script],
                cwd=tmp, env=env, capture_output=True, text=True,
            )
            return proc.returncode, out.read_text(), proc.stderr

    def test_selection_uses_exact_tag_guide_when_present(self):
        code, output, _ = self._run_selection("v0.2.0", True, True)
        self.assertEqual(code, 0)
        self.assertIn("source=release-src/docs/user-guide.md", output)

    def test_selection_prerelease_exact_tag_guide_works(self):
        code, output, _ = self._run_selection("v1.2.3-rc.1", True, True)
        self.assertEqual(code, 0)
        self.assertIn("source=release-src/docs/user-guide.md", output)

    def test_selection_v010_without_exact_guide_uses_snapshot(self):
        code, output, _ = self._run_selection("v0.1.0", False, True)
        self.assertEqual(code, 0)
        self.assertIn("source=docs/releases/v0.1.0/user-guide.md", output)

    def test_selection_other_tag_without_exact_guide_fails_hard(self):
        # A valid semver tag lacking an exact-tag guide must fail even when
        # the v0.1.0 snapshot exists: no tag may consume another's snapshot.
        for tag in ("v0.0.9", "v0.3.0", "v2.0.0", "v9.9.9-rc.1"):
            code, output, stderr = self._run_selection(tag, False, True)
            self.assertNotEqual(code, 0, f"{tag} must fail without a guide")
            self.assertNotIn("source=", output)
            self.assertIn("v0.1.0", stderr)

    def test_selection_v010_with_missing_snapshot_fails(self):
        code, output, _ = self._run_selection("v0.1.0", False, False)
        self.assertNotEqual(code, 0)
        self.assertNotIn("source=", output)

    def test_backfill_requires_existing_non_draft_release(self):
        self.assertIn("workflow_dispatch", self.text)
        self.assertIn("gh release view", self.text)
        self.assertIn("isDraft", self.text)
        self.assertNotIn("gh release create", self.text)
        self.assertNotIn("gh release edit", self.text)

    def test_deterministic_date_from_tag_commit(self):
        self.assertIn("--format=%cd", self.text)
        self.assertIn("--date=format-local:%Y-%m-%d", self.text)
        self.assertIn("TZ=UTC", self.text)
        self.assertNotIn("date +%", self.text.replace("--date=format-local", ""))

    def test_concurrency_per_release_without_cancel(self):
        self.assertRegex(
            self.text,
            r"group:\s*release-user-guide-\$\{\{ github\.event\.release\.tag_name"
            r" \|\| inputs\.tag \}\}",
        )
        self.assertIn("cancel-in-progress: false", self.text)

    def test_rerun_replaces_asset_and_asserts_single_asset(self):
        self.assertIn("--clobber", self.text)
        self.assertIn("exactly one", self.raw.lower())
        upload_job = self.text[self.text.index("  upload:"):]
        self.assertIn('if [ "$count" != "1" ]', upload_job)

    def test_upload_depends_on_successful_build_and_validation(self):
        upload_job = self.text[self.text.index("  upload:"):]
        self.assertIn("needs: build", upload_job)
        build_job = self.text[
            self.text.index("  build:"):self.text.index("  upload:")
        ]
        self.assertIn("validate_pdf.py", build_job)
        self.assertIn("--require-hashes", build_job)
        self.assertIn("if-no-files-found: error", build_job)

    def test_draft_releases_are_guarded(self):
        self.assertIn("!github.event.release.draft", self.raw)

    def test_asset_name_pattern(self):
        self.assertIn(f"{ASSET_PREFIX}$TAG.pdf", self.raw)


class DocsPdfWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = PR_WORKFLOW.read_text()
        cls.text = strip_comments(cls.raw)

    def test_triggers_on_relevant_pull_request_paths(self):
        self.assertIn("pull_request:", self.text)
        for path in (
            '"app/**"', '"docs/**"', '"tools/pdf/**"',
            '".github/workflows/**"', '"README.md"', '"CONTRIBUTING.md"',
            '"Dockerfile"', '"compose.yaml"', '"compose.proxy.yaml"',
        ):
            self.assertIn(path, self.text, f"missing PR path filter {path}")
        for forbidden in ("release:", "workflow_dispatch:", "schedule:"):
            self.assertNotIn(forbidden, self.text)

    def test_read_only_permissions(self):
        entries = dict(
            re.findall(
                r"^[ \t]*([a-z-]+):\s*(read|write|none)$", self.text, re.MULTILINE
            )
        )
        self.assertEqual(entries, {"contents": "read"})

    def test_all_actions_are_sha_pinned(self):
        for match in re.finditer(r"uses:\s*(\S+)", self.text):
            name, _, ref = match.group(1).partition("@")
            self.assertRegex(
                ref, r"^[0-9a-f]{40}$", f"action {name} must be pinned by commit SHA"
            )

    def test_builds_and_validates_both_guides(self):
        self.assertIn("build_pdf.py", self.text)
        self.assertIn("validate_pdf.py", self.text)
        self.assertIn("docs/releases/v0.1.0/user-guide.md", self.text)
        self.assertIn("--require-hashes", self.text)

    def test_no_upload_or_release_interaction(self):
        self.assertNotIn("gh release", self.text)
        self.assertNotIn("contents: write", self.text)


class PdfToolingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = BUILD_SCRIPT.read_text()
        cls.validate = VALIDATE_SCRIPT.read_text()

    def test_renderer_is_digest_pinned(self):
        self.assertRegex(
            self.build, r"pandoc/latex@sha256:\s*\"?\n?\s*\"[0-9a-f]{64}\"",
        )
        self.assertNotIn(":latest", self.build)

    def test_strict_version_validation_in_both_scripts(self):
        halves = (
            r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)",
            r"(-[0-9A-Za-z]+(\.[0-9A-Za-z]+)*)?$",
        )
        for text, name in ((self.build, "build"), (self.validate, "validate")):
            for half in halves:
                self.assertIn(half, text, f"{name} must share the tag regex")

    def test_build_rejects_missing_placeholders_and_never_rewrites_source(self):
        self.assertIn("{{VERSION}}", self.build)
        self.assertIn("{{GENERATED_ON}}", self.build)
        self.assertIn("TemporaryDirectory", self.build)
        self.assertNotIn("source.write_text", self.build)

    def test_build_is_deterministic_and_offline(self):
        self.assertIn("SOURCE_DATE_EPOCH", self.build)
        self.assertIn("head_commit_date", self.build)
        self.assertIn('"--network", "none"', self.build)
        self.assertNotIn("datetime.date.today", self.build)
        self.assertNotIn("datetime.now", self.build)

    def test_build_uses_argument_vectors_not_shell(self):
        self.assertNotIn("shell=True", self.build)
        self.assertNotIn("os.system", self.build)

    def test_asset_name_template(self):
        self.assertIn(
            'ASSET_NAME_TEMPLATE = "picture-postcard-manager-user-guide-'
            '{version}.pdf"',
            self.build,
        )

    def test_validator_checks_the_promised_properties(self):
        for marker in (
            "%PDF-", "extract_text", "{{VERSION}}", "{{GENERATED_ON}}",
            "outline", "/Link", "FontFile",
            "https://github.com/schmidt-software/picture-postcard-manager",
        ):
            self.assertIn(marker, self.validate)

    def test_validator_dependency_is_hash_pinned(self):
        requirements = VALIDATE_REQUIREMENTS.read_text()
        self.assertRegex(requirements, r"(?m)^pypdf==\d+\.\d+\.\d+")
        self.assertEqual(requirements.count("--hash=sha256:"), 2)
        self.assertNotIn(">=", requirements)

    def test_generated_pdfs_are_ignored_by_git(self):
        self.assertIn("dist/", (ROOT / ".gitignore").read_text())


class SnapshotGuideTest(unittest.TestCase):
    """The retrospective v0.1.0 snapshot must stay honest and buildable."""

    @classmethod
    def setUpClass(cls):
        cls.snapshot = SNAPSHOT.read_text()
        cls.flat = re.sub(r"\s+", " ", re.sub(r"(?m)^> ", "", cls.snapshot))

    def test_snapshot_exists_with_placeholders(self):
        self.assertIn('version: "{{VERSION}}"', self.snapshot)
        self.assertIn('generated_on: "{{GENERATED_ON}}"', self.snapshot)
        self.assertNotRegex(self.snapshot, r"\bv\d+\.\d+\.\d+-guide\b")

    def test_snapshot_declares_retrospective_provenance(self):
        self.assertIn("Provenance", self.snapshot)
        self.assertIn("written after the release it describes", self.flat)
        self.assertIn("retrospectively", self.snapshot)

    def test_snapshot_matches_v010_not_current_main(self):
        # v0.1.0 facts that differ from main: visible path fields, place and
        # region fields/filters/sort, single-tag filter, schema version 5,
        # upload-on-select, no version footer or /api/version.
        for fact in (
            "Front image path",
            "Back image path",
            "**Place**",
            "**Region**",
            "schema version 5",
            "The previous path was kept.",
            "Please enter the front image path.",
        ):
            self.assertIn(fact, self.flat, f"missing v0.1.0 fact: {fact!r}")
        # Features that v0.1.0 does not have must not be documented.
        for absent in (
            "/api/version",
            "Add tag filter",
            "?tag=Wien&tag=Bridge",
            "Tag suggestions",
            "No image selected. Opens the file picker.",
            "schema 6",
        ):
            self.assertNotIn(absent, self.snapshot, f"post-v0.1.0 fact: {absent!r}")
        self.assertIn(
            "does not display its version", self.snapshot,
            "the snapshot must say v0.1.0 has no version display",
        )

    def test_snapshot_documents_the_published_v010_ghcr_image(self):
        # v0.1.0 DID publish a multi-arch GHCR image (release-image.yml
        # existed at that tag and the release body documents it). The
        # snapshot must document the correct pull reference and the actual
        # tag aliases of that release.
        self.assertIn(
            "ghcr.io/schmidt-software/picture-postcard-manager:0.1.0",
            self.snapshot,
        )
        self.assertIn("linux/amd64", self.flat)
        self.assertIn("linux/arm64", self.flat)
        self.assertIn("`v0.1.0` and", self.flat)
        self.assertIn("`latest`", self.flat)
        # Only the 0.1.0 release's own references; no other version tag and
        # no bare moving-tag pull command.
        refs = re.findall(
            r"picture-postcard-manager:([0-9A-Za-z.\-]+)", self.snapshot
        )
        self.assertTrue(refs, "expected explicit image references")
        self.assertEqual(set(refs), {"0.1.0"})

    def test_snapshot_keeps_no_hard_coded_release_version_outside_its_keys(self):
        # The only literal version strings allowed are the tag key in the
        # source path (docs/releases/v0.1.0/), the GHCR image references of
        # this release, and its tag aliases in the image section.
        body = self.snapshot.replace("docs/releases/v0.1.0/user-guide.md", "")
        body = body.replace(
            "ghcr.io/schmidt-software/picture-postcard-manager:0.1.0", ""
        )
        body = body.replace("`v0.1.0`", "")
        self.assertNotRegex(body, r"(?<![\d.])v?\d+\.\d+\.\d+(?![.\d])")

    def test_current_guide_still_has_placeholders(self):
        guide = GUIDE.read_text()
        self.assertIn('version: "{{VERSION}}"', guide)
        self.assertIn('generated_on: "{{GENERATED_ON}}"', guide)


if __name__ == "__main__":
    unittest.main()
