"""Full backup and restore of postcard records and managed images.

A backup is one portable, gzip-compressed tar archive (backup format
version 1) containing:

    manifest.json    archive metadata: format marker, backup format version,
                     database schema version, creation time, postcard count,
                     per-image size and SHA-256 checksum, and the names of
                     referenced images that were missing at backup time
    postcards.json   the regular JSON export payload (same content as
                     ``GET /api/export``)
    images/<name>    the managed image files (generated upload names only)
                     referenced by any postcard's front or back image path

Creating a backup never modifies live data: the database is opened
read-only and image files are only read. Only referenced managed files are
included; orphaned uploads and the derived ``images/thumbs/`` cache are not.
A referenced image that is missing on disk is recorded in the manifest and
reported, and the backup still succeeds.

Restoring validates the complete archive before any mutation: member names
are checked against a strict allowlist (no path traversal, no symlinks, no
unexpected files), checksums and image signatures are verified, and the
records are imported into a staged copy of the database first. Only after
everything succeeded are the images placed (each with an atomic rename) and
the staged database moved over the live one as the final committing step, so
an interrupted restore never leaves a partially mutated database. Restoring
into an instance that already contains postcards, or overwriting an existing
image file with different content, requires the explicit ``--force`` flag;
``--dry-run`` prints the full preview without changing anything.

Run with:

    python3 -m app.backup create [--output PATH] [--db PATH] [--image-dir PATH]
    python3 -m app.backup restore ARCHIVE [--mode append|replace]
            [--dry-run] [--force] [--db PATH] [--image-dir PATH]

Stop the application while creating or restoring a backup so the copy is
consistent; restore refuses nothing by itself but operates on the files
directly, exactly like the documented manual ``tar`` procedure.
"""

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from app import images as image_store
from app.cleanup import referenced_names
from app.db import SCHEMA_VERSION, Database

FORMAT = "picture-postcard-manager-backup"
BACKUP_VERSION = 1
MANIFEST_NAME = "manifest.json"
POSTCARDS_NAME = "postcards.json"
IMAGE_PREFIX = "images/"
# Caps match the application: images use the upload limit, the records
# payload uses the API import body limit, the manifest is small metadata.
MAX_POSTCARDS_BYTES = 50 * 1024 * 1024
MAX_MANIFEST_BYTES = 10 * 1024 * 1024
MANIFEST_FIELDS = {"format", "backup_version", "schema_version", "created_at",
                   "postcard_count", "images", "missing_images"}
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
CHUNK_BYTES = image_store.CHUNK_BYTES


class BackupError(ValueError):
    """A backup or restore failed validation; nothing was mutated."""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _open_readonly(db_path):
    """Open the SQLite database strictly read-only (never migrates)."""
    path = Path(db_path).resolve()
    uri = "file:" + quote(str(path)) + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _export_readonly(db_path):
    """Return the JSON export payload without opening the database writable.

    The regular Database class migrates older schemas on open, which would
    modify live data; a backup must never do that. The database is therefore
    required to be at the current schema version already (start the matching
    application version once to migrate it first).
    """
    if not Path(db_path).is_file():
        raise BackupError(f"database not found: {db_path}")
    try:
        conn = _open_readonly(db_path)
    except sqlite3.Error as exc:
        raise BackupError(f"cannot open database read-only: {exc}") from exc
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version != SCHEMA_VERSION:
            raise BackupError(
                f"database schema version {version} does not match the "
                f"current version {SCHEMA_VERSION}; run the matching "
                "application version once to migrate before backing up")
        rows = conn.execute("SELECT * FROM postcards ORDER BY id DESC").fetchall()
    except sqlite3.Error as exc:
        raise BackupError(f"cannot read database: {exc}") from exc
    finally:
        conn.close()
    postcards = []
    for row in rows:
        record = dict(row)
        try:
            record["tags"] = json.loads(record["tags"])
        except json.JSONDecodeError as exc:
            raise BackupError(
                f"postcard {record.get('id')} has corrupt tags: {exc}") from exc
        postcards.append(record)
    return {
        "format": "picture-postcard-manager",
        "schema_version": SCHEMA_VERSION,
        "exported_at": _now(),
        "postcards": postcards,
    }


def _collect_images(image_dir, postcards):
    """Return ([(name, path, size, sha256)], [missing names]) for the backup.

    Only referenced generated names that exist as regular, non-symlinked
    files directly inside the image directory are included, mirroring the
    serving and cleanup rules. The derived thumbnail cache is never included.
    """
    root = Path(image_dir)
    included, missing = [], []
    for name in sorted(referenced_names(postcards)):
        path = root / name
        if path.is_symlink() or not path.is_file():
            missing.append(name)
            continue
        size = path.stat().st_size
        if size > image_store.MAX_IMAGE_BYTES:
            raise BackupError(f"image is larger than the upload limit: {path}")
        digest = hashlib.sha256()
        with open(path, "rb") as file:
            while chunk := file.read(CHUNK_BYTES):
                digest.update(chunk)
        included.append((name, path, size, digest.hexdigest()))
    return included, missing


def _json_bytes(data):
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


def _add_member(tar, name, data, mtime):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = 0o644
    info.mtime = mtime
    tar.addfile(info, io.BytesIO(data))


def create_backup(db_path, image_dir, output=None, out=sys.stdout):
    """Create a backup archive and return its path. Never modifies live data."""
    payload = _export_readonly(db_path)
    included, missing = _collect_images(image_dir, payload["postcards"])
    created_at = payload["exported_at"]
    manifest = {
        "format": FORMAT,
        "backup_version": BACKUP_VERSION,
        "schema_version": SCHEMA_VERSION,
        "created_at": created_at,
        "postcard_count": len(payload["postcards"]),
        "images": [{"name": name, "size": size, "sha256": sha}
                   for name, _path, size, sha in included],
        "missing_images": missing,
    }
    default_name = ("ppm-backup-"
                    + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
                    + ".tar.gz")
    target = Path(output) if output else Path(default_name)
    if target.is_dir():
        target = target / default_name
    if target.exists():
        raise BackupError(f"output file already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    mtime = int(datetime.now(timezone.utc).timestamp())
    fd, temp_name = tempfile.mkstemp(prefix=".ppm-backup-", suffix=".tar.gz",
                                     dir=target.parent)
    os.close(fd)
    temp = Path(temp_name)
    try:
        with tarfile.open(temp, "w:gz") as tar:
            _add_member(tar, MANIFEST_NAME, _json_bytes(manifest), mtime)
            _add_member(tar, POSTCARDS_NAME, _json_bytes(payload), mtime)
            for name, path, size, _sha in included:
                info = tarfile.TarInfo(IMAGE_PREFIX + name)
                info.size = size
                info.mode = 0o644
                info.mtime = mtime
                with open(path, "rb") as file:
                    tar.addfile(info, file)
        os.replace(temp, target)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    for name in missing:
        print(f"Warning: referenced image is missing and was not archived: {name}",
              file=out)
    print(f"Backed up {len(payload['postcards'])} postcard(s) and "
          f"{len(included)} image(s) to {target}", file=out)
    return target


# --- restore ----------------------------------------------------------------


def _validate_manifest(manifest):
    if not isinstance(manifest, dict):
        raise BackupError("manifest must be an object")
    unknown = set(manifest) - MANIFEST_FIELDS
    if unknown:
        raise BackupError(f"unknown manifest fields: {', '.join(sorted(unknown))}")
    if manifest.get("format") != FORMAT:
        raise BackupError("not a picture-postcard-manager backup archive")
    version = manifest.get("backup_version")
    if type(version) is not int or version != BACKUP_VERSION:
        raise BackupError(f"unsupported backup format version: {version!r}")
    if type(manifest.get("schema_version")) is not int:
        raise BackupError("manifest schema_version must be an integer")
    if type(manifest.get("postcard_count")) is not int:
        raise BackupError("manifest postcard_count must be an integer")
    entries = manifest.get("images")
    if not isinstance(entries, list):
        raise BackupError("manifest images must be a list")
    images = {}
    for entry in entries:
        if (not isinstance(entry, dict)
                or set(entry) != {"name", "size", "sha256"}):
            raise BackupError("manifest image entries must have name, size and sha256")
        name, size, sha = entry["name"], entry["size"], entry["sha256"]
        if not isinstance(name, str) or not image_store.NAME_PATTERN.fullmatch(name):
            raise BackupError(f"manifest image name is not a generated name: {name!r}")
        if type(size) is not int or not 0 < size <= image_store.MAX_IMAGE_BYTES:
            raise BackupError(f"manifest image size is invalid: {name}")
        if not isinstance(sha, str) or not SHA256_HEX.fullmatch(sha):
            raise BackupError(f"manifest image checksum is invalid: {name}")
        if name in images:
            raise BackupError(f"duplicate manifest image: {name}")
        images[name] = (size, sha)
    missing = manifest.get("missing_images", [])
    if not isinstance(missing, list) or not all(
            isinstance(name, str) and image_store.NAME_PATTERN.fullmatch(name)
            for name in missing):
        raise BackupError("manifest missing_images must be a list of generated names")
    return images, list(missing)


def _load_json_member(tar, member, limit, what):
    if member.size > limit:
        raise BackupError(f"{what} exceeds the size limit")
    data = tar.extractfile(member).read(limit + 1)
    if len(data) != member.size:
        raise BackupError(f"{what} is truncated")
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupError(f"{what} is not valid JSON: {exc}") from exc


def _checked_members(tar):
    """Return {name: member} after enforcing the strict member allowlist.

    Every member must be a regular file whose name is exactly manifest.json,
    postcards.json, or images/ plus a generated upload name. This rejects
    path traversal (.., absolute paths, backslashes), symlinks, hard links,
    directories, devices and any unexpected content before extraction.
    """
    members = {}
    for member in tar.getmembers():
        if not member.isreg():
            raise BackupError(f"unsupported archive member type: {member.name}")
        name = member.name
        if name in (MANIFEST_NAME, POSTCARDS_NAME):
            pass
        elif (name.startswith(IMAGE_PREFIX)
                and image_store.NAME_PATTERN.fullmatch(name[len(IMAGE_PREFIX):])):
            if member.size > image_store.MAX_IMAGE_BYTES:
                raise BackupError(f"archived image exceeds the upload limit: {name}")
        else:
            raise BackupError(f"unexpected archive member: {name}")
        if name in members:
            raise BackupError(f"duplicate archive member: {name}")
        members[name] = member
    for required in (MANIFEST_NAME, POSTCARDS_NAME):
        if required not in members:
            raise BackupError(f"archive is missing {required}")
    return members


def _extract_image(tar, member, dest):
    """Extract one validated image member to dest; return its SHA-256 hex."""
    file = tar.extractfile(member)
    digest = hashlib.sha256()
    first = file.read(min(member.size, CHUNK_BYTES))
    extension = member.name.rsplit(".", 1)[1]
    if image_store.detect_extension(first) != extension:
        raise BackupError(
            f"archived image content does not match its extension: {member.name}")
    written = 0
    with open(dest, "wb") as target:
        chunk = first
        while chunk:
            digest.update(chunk)
            target.write(chunk)
            written += len(chunk)
            chunk = file.read(min(member.size - written, CHUNK_BYTES))
    if written != member.size:
        raise BackupError(f"archived image is truncated: {member.name}")
    return digest.hexdigest()


def _file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        while chunk := file.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _existing_record_count(db_path):
    if not Path(db_path).is_file():
        return 0
    try:
        conn = _open_readonly(db_path)
    except sqlite3.Error as exc:
        raise BackupError(f"cannot open existing database: {exc}") from exc
    try:
        return conn.execute("SELECT COUNT(*) FROM postcards").fetchone()[0]
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


def restore_backup(archive, db_path, image_dir, mode="replace",
                   dry_run=False, force=False, out=sys.stdout):
    """Validate and restore a backup archive; return a summary dict.

    The whole archive is validated and the records are imported into a
    staged copy of the database before anything is mutated. Restoring when
    postcards already exist, or overwriting an image file whose content
    differs, requires force=True. With dry_run=True the full preview is
    printed and nothing is changed.
    """
    if mode not in ("append", "replace"):
        raise BackupError("mode must be 'append' or 'replace'")
    archive = Path(archive)
    if not archive.is_file():
        raise BackupError(f"archive not found: {archive}")
    db_path = Path(db_path)
    image_dir = Path(image_dir)
    staging = Path(tempfile.mkdtemp(prefix=".ppm-restore-"))
    try:
        plan = _prepare(archive, db_path, image_dir, mode, staging)
        _report(plan, mode, dry_run, out)
        if dry_run:
            print("Dry run: no changes were made.", file=out)
            return plan
        if (plan["existing_records"] or plan["conflicting_images"]) and not force:
            details = []
            if plan["existing_records"]:
                details.append(f"{plan['existing_records']} existing postcard(s)")
            if plan["conflicting_images"]:
                details.append(
                    f"{len(plan['conflicting_images'])} conflicting image file(s): "
                    + ", ".join(plan["conflicting_images"]))
            raise BackupError(
                "the target instance is not empty ("
                + "; ".join(details)
                + "); re-run with --force to confirm, or use --dry-run to preview")
        _commit(plan, db_path, image_dir)
        print(f"Restored {plan['imported']} postcard(s) and "
              f"{len(plan['restore_images'])} image(s) (mode: {mode}).", file=out)
        return plan
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _prepare(archive, db_path, image_dir, mode, staging):
    """Validate the archive completely and stage the restore without mutation."""
    try:
        tar = tarfile.open(archive, "r:gz", errorlevel=2)
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise BackupError(f"archive is corrupt or not a backup archive: {exc}") from exc
    image_staging = staging / "images"
    image_staging.mkdir()
    try:
        with tar:
            members = _checked_members(tar)
            manifest = _load_json_member(
                tar, members[MANIFEST_NAME], MAX_MANIFEST_BYTES, "manifest.json")
            manifest_images, manifest_missing = _validate_manifest(manifest)
            payload = _load_json_member(
                tar, members[POSTCARDS_NAME], MAX_POSTCARDS_BYTES, "postcards.json")
            if (not isinstance(payload, dict)
                    or not isinstance(payload.get("postcards"), list)):
                raise BackupError("postcards.json must be an export payload")
            if payload.get("schema_version") != manifest["schema_version"]:
                raise BackupError(
                    "manifest and postcards.json schema versions do not match")
            if manifest["postcard_count"] != len(payload["postcards"]):
                raise BackupError(
                    "manifest postcard_count does not match postcards.json")
            archived = {name[len(IMAGE_PREFIX):]: member
                        for name, member in members.items()
                        if name.startswith(IMAGE_PREFIX)}
            if set(archived) != set(manifest_images):
                raise BackupError("archive images do not match the manifest")
            for name, member in sorted(archived.items()):
                size, sha = manifest_images[name]
                if member.size != size:
                    raise BackupError(f"archived image size mismatch: {name}")
                if _extract_image(tar, member, image_staging / name) != sha:
                    raise BackupError(f"archived image checksum mismatch: {name}")
    except (tarfile.TarError, OSError, EOFError) as exc:
        if isinstance(exc, BackupError):
            raise
        raise BackupError(f"archive is corrupt or not a backup archive: {exc}") from exc
    # Stage the database: copy the live one (consistently, via the SQLite
    # backup API) and import into the copy. Any failure aborts before any
    # live file is touched.
    staged_db = staging / "postcards.db"
    existing = _existing_record_count(db_path)
    if db_path.is_file():
        source = _open_readonly(db_path)
        try:
            dest = sqlite3.connect(staged_db)
            try:
                source.backup(dest)
            finally:
                dest.close()
        finally:
            source.close()
    try:
        db = Database(str(staged_db))
    except (sqlite3.Error, ValueError) as exc:
        raise BackupError(f"existing database cannot be prepared: {exc}") from exc
    try:
        imported = db.import_data(payload, mode)
    except ValueError as exc:
        raise BackupError(f"backup records failed validation: {exc}") from exc
    finally:
        db.close()
    # Classify images against the live image directory.
    restore_images, identical, conflicting = [], [], []
    referenced = referenced_names(
        [entry for entry in payload["postcards"] if isinstance(entry, dict)])
    missing = sorted((referenced | set(manifest_missing)) - set(archived))
    for name in sorted(archived):
        target = image_dir / name
        if target.is_symlink():
            conflicting.append(name)
        elif target.is_file():
            if _file_sha256(target) == manifest_images[name][1]:
                identical.append(name)
            else:
                conflicting.append(name)
        else:
            restore_images.append(name)
    return {
        "archive": str(archive),
        "backup_version": manifest["backup_version"],
        "schema_version": manifest["schema_version"],
        "created_at": manifest.get("created_at"),
        "postcards": len(payload["postcards"]),
        "imported": imported,
        "existing_records": existing,
        "restore_images": restore_images,
        "identical_images": identical,
        "conflicting_images": conflicting,
        "missing_images": missing,
        "staged_db": staged_db,
        "staged_images": image_staging,
    }


def _report(plan, mode, dry_run, out):
    print(f"Archive: {plan['archive']}", file=out)
    print(f"Backup format version {plan['backup_version']}, "
          f"schema version {plan['schema_version']}, "
          f"created {plan['created_at']}", file=out)
    print(f"Postcards to restore: {plan['postcards']} (mode: {mode})", file=out)
    if plan["existing_records"]:
        fate = "replaced" if mode == "replace" else "kept"
        print(f"Existing postcards: {plan['existing_records']} (will be {fate})",
              file=out)
    print(f"Images: {len(plan['restore_images'])} to restore, "
          f"{len(plan['identical_images'])} already present and identical, "
          f"{len(plan['conflicting_images'])} conflicting", file=out)
    for name in plan["conflicting_images"]:
        print(f"Conflicting image file (content differs): {name}", file=out)
    for name in plan["missing_images"]:
        print(f"Warning: referenced image is not in the archive: {name}", file=out)


def _commit(plan, db_path, image_dir):
    """Apply the staged restore. The database replacement is the final step."""
    image_dir.mkdir(parents=True, exist_ok=True)
    to_place = plan["restore_images"] + plan["conflicting_images"]
    for name in to_place:
        staged = plan["staged_images"] / name
        fd, temp_name = tempfile.mkstemp(prefix=".ppm-restore-", dir=image_dir)
        os.close(fd)
        try:
            shutil.copyfile(staged, temp_name)
            os.chmod(temp_name, 0o644)
            os.replace(temp_name, image_dir / name)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise
    db_path.parent.mkdir(parents=True, exist_ok=True)
    os.replace(plan["staged_db"], db_path)
    # The replaced database carries no WAL state; stale sidecar files of the
    # previous database must not be applied to it.
    for suffix in ("-wal", "-shm"):
        Path(str(db_path) + suffix).unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Create or restore a full backup (records and images).")
    sub = parser.add_subparsers(dest="command", required=True)
    db_default = os.environ.get("PPM_DB_PATH", "data/postcards.db")
    common = {
        "--db": dict(default=db_default,
                     help="path to the SQLite database (default: PPM_DB_PATH "
                          "or data/postcards.db)"),
        "--image-dir": dict(default=os.environ.get("PPM_IMAGE_DIR"),
                            help="image directory (default: PPM_IMAGE_DIR or "
                                 "'images' next to the database)"),
    }
    create = sub.add_parser("create", help="create a backup archive")
    create.add_argument("--output",
                        help="archive file or directory to write "
                             "(default: ppm-backup-<timestamp>.tar.gz)")
    restore = sub.add_parser("restore", help="restore a backup archive")
    restore.add_argument("archive", help="backup archive to restore")
    restore.add_argument("--mode", choices=("replace", "append"), default="replace",
                         help="replace keeps archived ids and uuids and removes "
                              "existing records; append adds copies with new ids "
                              "(default: replace)")
    restore.add_argument("--dry-run", action="store_true",
                         help="validate and preview only; change nothing")
    restore.add_argument("--force", action="store_true",
                         help="confirm restoring when postcards already exist "
                              "or image files would be overwritten")
    for command in (create, restore):
        for flag, options in common.items():
            command.add_argument(flag, **options)
    args = parser.parse_args(argv)
    image_dir = args.image_dir or Path(args.db).parent / "images"
    try:
        if args.command == "create":
            create_backup(args.db, image_dir, args.output)
        else:
            restore_backup(args.archive, args.db, image_dir, mode=args.mode,
                           dry_run=args.dry_run, force=args.force)
    except BackupError as exc:
        parser.exit(1, f"error: {exc}\n")


if __name__ == "__main__":
    main()
