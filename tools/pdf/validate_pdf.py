"""Validate a generated user-guide PDF (Refs #49).

Checks, without rendering anything:

- the file starts with the ``%PDF-`` magic and parses as a PDF,
- the page count is plausible for the full guide,
- the document title matches the guide,
- the injected release version appears in the extracted (selectable) text,
- neither ``{{VERSION}}`` nor ``{{GENERATED_ON}}`` leaked into the output,
- the document has an outline (PDF bookmarks) and link annotations,
- the public project URL survives as a working external link,
- every font used by the document is embedded.

Usage:

    python3 tools/pdf/validate_pdf.py --pdf dist/…pdf --version v0.2.0

Requires pypdf, installed from the hash-pinned
``tools/pdf/requirements-validate.txt``. Everything else is standard library.
"""

import argparse
import pathlib
import re
import sys

from pypdf import PdfReader
from pypdf.generic import IndirectObject

EXPECTED_TITLE = "Picture Postcard Manager User Guide"
PROJECT_URL = "https://github.com/schmidt-software/picture-postcard-manager"
MIN_PAGES = 10
VERSION_PATTERN = re.compile(
    r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(-[0-9A-Za-z]+(\.[0-9A-Za-z]+)*)?$"
)


def _resolve(obj):
    return obj.get_object() if isinstance(obj, IndirectObject) else obj


def _font_embedded(font):
    font = _resolve(font)
    descendants = font.get("/DescendantFonts")
    if descendants is not None:
        return all(_font_embedded(item) for item in _resolve(descendants))
    descriptor = font.get("/FontDescriptor")
    if descriptor is None:
        # Type3 fonts carry their glyph procedures inline; the base-14
        # standard fonts (no descriptor) would NOT be embedded.
        return font.get("/Subtype") == "/Type3"
    descriptor = _resolve(descriptor)
    return any(
        key in descriptor for key in ("/FontFile", "/FontFile2", "/FontFile3")
    )


def _iter_fonts(reader):
    for page in reader.pages:
        resources = _resolve(page.get("/Resources") or {})
        fonts = _resolve(resources.get("/Font") or {})
        for name, font in fonts.items():
            yield name, font


def _link_uris(reader):
    uris, internal = set(), 0
    for page in reader.pages:
        for annotation in page.get("/Annots") or []:
            annotation = _resolve(annotation)
            if annotation.get("/Subtype") != "/Link":
                continue
            action = _resolve(annotation.get("/A") or {})
            uri = action.get("/URI")
            if uri:
                uris.add(str(uri))
            else:
                internal += 1
    return uris, internal


def validate(pdf_path, version):
    errors = []
    path = pathlib.Path(pdf_path)
    raw = path.read_bytes()
    if not raw.startswith(b"%PDF-"):
        return [f"{path} does not start with the %PDF- magic"]

    reader = PdfReader(path)
    pages = len(reader.pages)
    if pages < MIN_PAGES:
        errors.append(f"only {pages} pages; expected at least {MIN_PAGES}")

    title = (reader.metadata or {}).get("/Title", "")
    if EXPECTED_TITLE not in str(title):
        errors.append(f"PDF title {title!r} does not contain {EXPECTED_TITLE!r}")

    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if not text.strip():
        errors.append("no selectable text could be extracted")
    if version not in text:
        errors.append(f"injected version {version!r} not found in the PDF text")
    for leaked in ("{{VERSION}}", "{{GENERATED_ON}}"):
        if leaked in text:
            errors.append(f"placeholder {leaked} leaked into the PDF")

    if not reader.outline:
        errors.append("PDF has no outline (bookmarks)")

    uris, internal_links = _link_uris(reader)
    if internal_links == 0:
        errors.append("PDF has no internal link annotations")
    if not any(uri.startswith(PROJECT_URL) for uri in uris):
        errors.append(f"project link {PROJECT_URL} not found among {sorted(uris)}")

    unembedded = sorted(
        {str(name) for name, font in _iter_fonts(reader) if not _font_embedded(font)}
    )
    if unembedded:
        errors.append(f"fonts not embedded: {', '.join(unembedded)}")

    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pdf", required=True, help="PDF file to validate")
    parser.add_argument("--version", required=True, help="expected release tag")
    args = parser.parse_args(argv)
    if not VERSION_PATTERN.match(args.version):
        print(f"error: {args.version!r} is not a strict semver release tag",
              file=sys.stderr)
        return 2
    errors = validate(args.pdf, args.version)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    reader = PdfReader(args.pdf)
    print(f"ok: {args.pdf} ({len(reader.pages)} pages, version {args.version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
