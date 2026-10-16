"""Docker-free consistency checks for the container build context.

The .dockerignore uses an allowlist (`**` excludes everything, `!...` entries
re-include files), so a Dockerfile COPY of a path that is not re-included
fails the build with "not found". These tests parse both files and assert that
every COPY source is covered, without needing Docker.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def copy_sources(dockerfile_text):
    """Return COPY source paths from a Dockerfile (build-context form only)."""
    sources = []
    for line in dockerfile_text.splitlines():
        words = line.split("#", 1)[0].split()
        if not words or words[0].upper() != "COPY":
            continue
        # Skip flags (--chown=..., --from=... copies outside the context).
        args = [w for w in words[1:] if not w.startswith("--")]
        if any(w.startswith("--from=") for w in words):
            continue
        sources.extend(args[:-1])  # Last argument is the destination.
    return sources


def allowlisted(dockerignore_text):
    """Return the re-included (!) patterns of an allowlist .dockerignore."""
    patterns = []
    for line in dockerignore_text.splitlines():
        line = line.strip()
        if line.startswith("!"):
            patterns.append(line[1:].rstrip("/"))
    return patterns


def covered(source, patterns):
    """True when `source` is re-included by one of the ! patterns."""
    source = source.rstrip("/")
    for pattern in patterns:
        if pattern == source or pattern == source + "/**":
            return True
        # A directory pattern covers the directory itself and its contents.
        if source.startswith(pattern + "/"):
            return True
    return False


class DockerignoreAllowlistTest(unittest.TestCase):
    def setUp(self):
        self.dockerfile = (ROOT / "Dockerfile").read_text()
        self.dockerignore = (ROOT / ".dockerignore").read_text()

    def test_dockerignore_is_an_allowlist(self):
        # The checks below only make sense for the `**` + `!...` style.
        self.assertEqual(self.dockerignore.split()[0], "**")

    def test_every_copied_path_is_allowlisted(self):
        patterns = allowlisted(self.dockerignore)
        sources = copy_sources(self.dockerfile)
        self.assertTrue(sources, "Dockerfile has no COPY instructions?")
        for source in sources:
            with self.subTest(source):
                self.assertTrue(
                    covered(source, patterns),
                    f"Dockerfile COPYs {source!r} but .dockerignore does not "
                    f"re-include it (add '!{source}'); docker build would fail",
                )

    def test_copied_paths_exist_in_the_repository(self):
        for source in copy_sources(self.dockerfile):
            with self.subTest(source):
                self.assertTrue((ROOT / source).exists(), source)

    def test_parser_helpers(self):
        self.assertEqual(copy_sources("COPY a b dest\nRUN x\nCOPY --chown=u f d"),
                         ["a", "b", "f"])
        self.assertEqual(copy_sources("COPY --from=builder /x /y"), [])
        self.assertEqual(allowlisted("**\n!app/\n!file.txt\nnoise\n"),
                         ["app", "file.txt"])
        self.assertTrue(covered("app", ["app"]))
        self.assertTrue(covered("app/sub/file.py", ["app"]))
        self.assertTrue(covered("requirements-optional.txt", ["requirements-optional.txt"]))
        self.assertFalse(covered("requirements-optional.txt", ["app", "Dockerfile"]))
        self.assertFalse(covered("application", ["app"]))
