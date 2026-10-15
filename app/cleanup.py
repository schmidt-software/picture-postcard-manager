"""Cleanup of orphaned uploaded images.

Lists or deletes generated image files in the image directory that no postcard
references. Only files with generated upload names (32 hex characters plus a
known extension) directly inside the image directory are considered; any file
whose name appears in a stored front or back image path is kept, also when the
path carries a query or fragment or is a full URL. Run with:

    python3 -m app.cleanup [--delete] [--db PATH] [--image-dir PATH]

Without ``--delete`` the command only lists orphaned files (dry run).
"""

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

from app.db import Database
from app.images import NAME_PATTERN


def referenced_names(postcards):
    """Return the set of generated file names referenced by any postcard.

    A file is referenced when its name is the final path segment of a stored
    front or back image path, regardless of how the path was entered. Stored
    values may be plain file paths, server paths with a query or fragment
    (``/images/<name>.png?v=1``), or full URLs; query strings, fragments and
    percent-encoding are ignored when extracting the name. Matching stays
    deliberately generous: every candidate interpretation of a value counts
    as a reference, so an ambiguous path keeps a file rather than orphaning
    it.
    """
    names = set()
    for postcard in postcards:
        for field in ("front_image_path", "back_image_path"):
            value = (postcard.get(field) or "").strip()
            if not value:
                continue
            # Consider the raw value, its URL path component (drops ?query
            # and #fragment, also for full http://host/... URLs), and the
            # percent-decoded form of each. Every match counts, which keeps
            # cleanup conservative for ambiguous values.
            candidates = {value, urlsplit(value).path}
            candidates.update({unquote(c) for c in set(candidates)})
            for candidate in candidates:
                name = candidate.replace("\\", "/").rsplit("/", 1)[-1]
                if NAME_PATTERN.fullmatch(name):
                    names.add(name)
    return names


def find_orphans(image_dir, postcards):
    """Return sorted orphaned generated image files directly in image_dir.

    Only regular, non-symlinked files whose names match the generated upload
    pattern and that no postcard references are returned. Other files (manual
    additions, directories, symlinks) are never considered.
    """
    root = Path(image_dir)
    if not root.is_dir():
        return []
    referenced = referenced_names(postcards)
    orphans = []
    for entry in os.scandir(root):
        if not NAME_PATTERN.fullmatch(entry.name):
            continue
        if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
            continue
        if entry.name not in referenced:
            orphans.append(Path(entry.path))
    return sorted(orphans)


def cleanup(db_path, image_dir, delete=False, out=sys.stdout):
    """List (and with delete=True remove) orphaned images; return the orphans."""
    db = Database(db_path)
    try:
        postcards = db.list()
    finally:
        db.close()
    orphans = find_orphans(image_dir, postcards)
    if not orphans:
        print("No orphaned images found.", file=out)
        return []
    for path in orphans:
        if delete:
            path.unlink()
            print(f"Deleted {path}", file=out)
        else:
            print(f"Orphaned {path}", file=out)
    if not delete:
        print(f"{len(orphans)} orphaned image(s). Re-run with --delete to remove them.",
              file=out)
    return orphans


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="List or delete uploaded images that no postcard references.",
    )
    parser.add_argument("--delete", action="store_true",
                        help="delete orphaned files (default: dry run that only lists them)")
    parser.add_argument("--db", default=os.environ.get("PPM_DB_PATH", "data/postcards.db"),
                        help="path to the SQLite database (default: PPM_DB_PATH or data/postcards.db)")
    parser.add_argument("--image-dir", default=os.environ.get("PPM_IMAGE_DIR"),
                        help="image directory (default: PPM_IMAGE_DIR or 'images' next to the database)")
    args = parser.parse_args(argv)
    if not Path(args.db).is_file():
        parser.error(f"database not found: {args.db}")
    image_dir = args.image_dir or Path(args.db).parent / "images"
    cleanup(args.db, image_dir, delete=args.delete)


if __name__ == "__main__":
    main()
