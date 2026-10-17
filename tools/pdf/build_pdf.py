"""Build the user-guide PDF with a pinned, containerized toolchain (Refs #49).

One command renders ``docs/user-guide.md`` into a release-named PDF:

    python3 tools/pdf/build_pdf.py --version v0.2.0

Design constraints (issue #49):

- The source file is never rewritten: the ``{{VERSION}}`` and
  ``{{GENERATED_ON}}`` placeholders are injected into a temporary copy only.
- The renderer is the ``pandoc/latex`` container image pinned by immutable
  digest, so a local build and a CI build use byte-identical tooling. No
  ``apt-get``/``latest`` dependency is involved.
- The generation date is deterministic: it defaults to the committer date of
  ``HEAD`` (or the commit given via ``--date``/``SOURCE_DATE_EPOCH``), never
  the wall clock, and the same date seeds ``SOURCE_DATE_EPOCH`` inside the
  container so repeated builds of the same commit produce identical PDFs.
- The version and date are validated strictly before use and are passed to
  the container via argument vectors only (no shell interpolation).

The script needs only the Python standard library and a Docker daemon.
"""

import argparse
import datetime
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

# Pinned renderer: pandoc 3.8.3 + TeX Live (xelatex) from the official
# pandoc/latex image. The digest is the immutable manifest-list digest of the
# pandoc/latex:3.8.3 tag; retagging upstream cannot change what this builds.
PANDOC_IMAGE = (
    "pandoc/latex@sha256:"
    "dd0dd153f681ec264094c04011e34459e8de61fe95712020ab4dfbff1117b015"
)  # pandoc/latex:3.8.3
PANDOC_IMAGE_TAG = "pandoc/latex:3.8.3"
# The image is published for linux/amd64 only; request that platform
# explicitly so arm64 hosts (Apple silicon) run it under emulation instead of
# failing with a manifest error.
PANDOC_PLATFORM = "linux/amd64"

# Strict release-tag pattern, identical to release-image.yml.
VERSION_PATTERN = re.compile(
    r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(-[0-9A-Za-z]+(\.[0-9A-Za-z]+)*)?$"
)
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

ASSET_NAME_TEMPLATE = "picture-postcard-manager-user-guide-{version}.pdf"

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = ROOT / "docs" / "user-guide.md"

PLACEHOLDERS = ("{{VERSION}}", "{{GENERATED_ON}}")


def asset_name(version):
    return ASSET_NAME_TEMPLATE.format(version=version)


def validate_version(version):
    if not VERSION_PATTERN.match(version):
        raise SystemExit(
            f"error: version {version!r} is not a strict semver release tag "
            "(vMAJOR.MINOR.PATCH[-prerelease])"
        )
    return version


def validate_date(date):
    if not DATE_PATTERN.match(date):
        raise SystemExit(f"error: date {date!r} is not an ISO-8601 date (YYYY-MM-DD)")
    try:
        datetime.date.fromisoformat(date)
    except ValueError as exc:
        raise SystemExit(f"error: date {date!r} is not a valid date: {exc}")
    return date


def head_commit_date(repo):
    """Committer date (UTC, YYYY-MM-DD) of HEAD: deterministic per commit."""
    result = subprocess.run(
        ["git", "-C", str(repo), "log", "-1", "--format=%cd",
         "--date=format-local:%Y-%m-%d"],
        capture_output=True, text=True, check=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "TZ": "UTC"},
    )
    return result.stdout.strip()


def inject(source_text, version, date):
    """Return the source with placeholders replaced; fail if they are absent."""
    for placeholder in PLACEHOLDERS:
        if placeholder not in source_text:
            raise SystemExit(
                f"error: placeholder {placeholder} not found in the guide "
                "source; refusing to build a PDF without injected metadata"
            )
    return source_text.replace("{{VERSION}}", version).replace(
        "{{GENERATED_ON}}", date
    )


def build(source, version, date, output_dir):
    source = pathlib.Path(source).resolve()
    if not source.is_file():
        raise SystemExit(f"error: guide source not found: {source}")
    text = source.read_text(encoding="utf-8")
    injected = inject(text, version, date)

    output_dir = pathlib.Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    final_pdf = output_dir / asset_name(version)

    epoch = int(
        datetime.datetime.fromisoformat(date)
        .replace(tzinfo=datetime.timezone.utc)
        .timestamp()
    )

    with tempfile.TemporaryDirectory(prefix="ppm-pdf-") as tmp:
        tmp_path = pathlib.Path(tmp)
        (tmp_path / "guide.md").write_text(injected, encoding="utf-8")
        command = [
            "docker", "run", "--rm",
            "--platform", PANDOC_PLATFORM,
            "--volume", f"{tmp_path}:/work",
            "--workdir", "/work",
            # Deterministic PDF timestamps: xelatex/xdvipdfmx honor
            # SOURCE_DATE_EPOCH, so the same commit yields the same bytes.
            "--env", f"SOURCE_DATE_EPOCH={epoch}",
            "--network", "none",
            PANDOC_IMAGE,
            "guide.md", "--output", "guide.pdf",
            # lualatex: fully reproducible output under SOURCE_DATE_EPOCH
            # (xelatex's xdvipdfmx randomizes font-subset tags per run).
            "--pdf-engine", "lualatex",
            "--toc", "--toc-depth", "3",
            "--number-sections",
            # The single H1 becomes the document title; H2 sections become
            # top-level PDF bookmarks and TOC entries.
            "--shift-heading-level-by", "-1",
            "--metadata", f"date=Version {version} — generated on {date}",
            # Standalone title page (article class, titlepage option), page
            # numbers, visible colored links, sane margins.
            "--variable", "classoption=titlepage",
            "--variable", "geometry:margin=2.5cm",
            "--variable", "colorlinks=true",
            "--variable", "linkcolor=blue",
            "--variable", "urlcolor=blue",
        ]
        completed = subprocess.run(command)
        if completed.returncode != 0:
            raise SystemExit(
                f"error: pandoc PDF build failed (exit {completed.returncode})"
            )
        built = tmp_path / "guide.pdf"
        if not built.is_file() or built.stat().st_size == 0:
            raise SystemExit("error: pandoc reported success but wrote no PDF")
        shutil.copyfile(built, final_pdf)
    return final_pdf


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--version", required=True,
        help="release tag to inject, e.g. v0.2.0 (strict semver, with the v)",
    )
    parser.add_argument(
        "--date", default=None,
        help="ISO date to inject as the generation date; defaults to the "
             "committer date of HEAD (deterministic, not the wall clock)",
    )
    parser.add_argument(
        "--source", default=str(DEFAULT_SOURCE),
        help="guide source file (default: docs/user-guide.md)",
    )
    parser.add_argument(
        "--output-dir", default=str(ROOT / "dist"),
        help="directory for the generated PDF (default: dist/, git-ignored)",
    )
    args = parser.parse_args(argv)

    version = validate_version(args.version)
    date = validate_date(args.date or head_commit_date(ROOT))
    pdf = build(args.source, version, date, args.output_dir)
    print(f"built {pdf}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
