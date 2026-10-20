"""Tests for the full backup and restore command (issue #69)."""

import io
import json
import os
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import backup as backup_module
from app.backup import (
    BACKUP_VERSION, FORMAT, BackupError, create_backup, main, restore_backup,
)
from app.db import SCHEMA_VERSION, Database

PNG = b"\x89PNG\r\n\x1a\n" + b"backup-test-front"
PNG_BACK = b"\x89PNG\r\n\x1a\n" + b"backup-test-back"
JPEG = b"\xff\xd8\xff\xe0" + b"backup-test-jpeg"
FRONT = "a" * 32 + ".png"
BACK = "b" * 32 + ".png"
UNREFERENCED = "c" * 32 + ".jpg"


class BackupFixture(unittest.TestCase):
    """A populated source instance and an independent target instance."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "source" / "postcards.db"
        self.image_dir = self.db_path.parent / "images"
        self.image_dir.mkdir(parents=True)
        (self.image_dir / FRONT).write_bytes(PNG)
        (self.image_dir / BACK).write_bytes(PNG_BACK)
        (self.image_dir / UNREFERENCED).write_bytes(JPEG)
        thumbs = self.image_dir / "thumbs"
        thumbs.mkdir()
        (thumbs / f"{'a' * 32}.400.jpg").write_bytes(JPEG)
        db = Database(str(self.db_path))
        try:
            self.first = db.create({
                "front_image_path": f"/images/{FRONT}",
                "back_image_path": f"/images/{BACK}",
                "year": "1910", "description": "Street view",
                "tags": ["Wien", "Gruß aus"],
            })
            self.second = db.create({"front_image_path": "/manual/scan.png"})
        finally:
            db.close()
        self.target_db = self.root / "target" / "postcards.db"
        self.target_images = self.target_db.parent / "images"

    def create(self, output=None):
        out = io.StringIO()
        archive = create_backup(self.db_path, self.image_dir,
                                output or self.root / "backup.tar.gz", out=out)
        return archive, out.getvalue()

    def restore(self, archive, **kwargs):
        out = io.StringIO()
        plan = restore_backup(archive, self.target_db, self.target_images,
                              out=out, **kwargs)
        return plan, out.getvalue()

    def records(self, db_path):
        db = Database(str(db_path))
        try:
            return db.list()
        finally:
            db.close()


class CreateBackupTest(BackupFixture):
    def test_backup_contains_manifest_export_and_referenced_images(self):
        archive, output = self.create()
        with tarfile.open(archive, "r:gz") as tar:
            names = sorted(tar.getnames())
            manifest = json.loads(tar.extractfile("manifest.json").read())
            payload = json.loads(tar.extractfile("postcards.json").read())
        self.assertEqual(names, sorted(
            ["manifest.json", "postcards.json",
             f"images/{FRONT}", f"images/{BACK}"]))
        self.assertEqual(manifest["format"], FORMAT)
        self.assertEqual(manifest["backup_version"], BACKUP_VERSION)
        self.assertEqual(manifest["schema_version"], SCHEMA_VERSION)
        self.assertEqual(manifest["postcard_count"], 2)
        self.assertEqual(sorted(e["name"] for e in manifest["images"]),
                         sorted([FRONT, BACK]))
        self.assertEqual(manifest["missing_images"], [])
        self.assertEqual(payload["schema_version"], SCHEMA_VERSION)
        self.assertEqual(len(payload["postcards"]), 2)
        self.assertIn("Backed up 2 postcard(s) and 2 image(s)", output)

    def test_backup_does_not_modify_live_data(self):
        before = {path: path.read_bytes()
                  for path in self.image_dir.rglob("*") if path.is_file()}
        db_bytes = self.db_path.read_bytes()
        self.create()
        self.assertEqual(self.db_path.read_bytes(), db_bytes)
        after = {path: path.read_bytes()
                 for path in self.image_dir.rglob("*") if path.is_file()}
        self.assertEqual(before, after)
        self.assertEqual([r["id"] for r in self.records(self.db_path)], [2, 1])

    def test_missing_referenced_image_is_reported_but_backup_succeeds(self):
        (self.image_dir / BACK).unlink()
        archive, output = self.create()
        self.assertIn(BACK, output)
        self.assertIn("missing", output)
        with tarfile.open(archive, "r:gz") as tar:
            manifest = json.loads(tar.extractfile("manifest.json").read())
            self.assertNotIn(f"images/{BACK}", tar.getnames())
        self.assertEqual(manifest["missing_images"], [BACK])

    def test_backup_requires_current_schema_and_existing_database(self):
        with self.assertRaisesRegex(BackupError, "not found"):
            create_backup(self.root / "missing.db", self.image_dir,
                          self.root / "x.tar.gz", out=io.StringIO())
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
        conn.close()
        with self.assertRaisesRegex(BackupError, "schema version"):
            self.create(self.root / "y.tar.gz")

    def test_backup_refuses_to_overwrite_existing_output(self):
        target = self.root / "existing.tar.gz"
        target.write_bytes(b"keep me")
        with self.assertRaisesRegex(BackupError, "already exists"):
            self.create(target)
        self.assertEqual(target.read_bytes(), b"keep me")


class RestoreBackupTest(BackupFixture):
    def test_round_trip_into_empty_instance(self):
        archive, _ = self.create()
        plan, output = self.restore(archive)
        self.assertEqual(plan["imported"], 2)
        self.assertEqual(self.records(self.target_db),
                         self.records(self.db_path))
        self.assertEqual((self.target_images / FRONT).read_bytes(), PNG)
        self.assertEqual((self.target_images / BACK).read_bytes(), PNG_BACK)
        self.assertFalse((self.target_images / UNREFERENCED).exists())
        self.assertIn("Restored 2 postcard(s) and 2 image(s)", output)
        # IDs, UUIDs, tags and timestamps are preserved.
        restored = {r["id"]: r for r in self.records(self.target_db)}
        self.assertEqual(restored[self.first["id"]]["uuid"], self.first["uuid"])
        self.assertEqual(restored[self.first["id"]]["tags"], ["Wien", "Gruß aus"])
        self.assertEqual(restored[self.first["id"]]["created_at"],
                         self.first["created_at"])

    def test_dry_run_changes_nothing(self):
        archive, _ = self.create()
        plan, output = self.restore(archive, dry_run=True)
        self.assertIn("Dry run: no changes were made.", output)
        self.assertIn("Postcards to restore: 2", output)
        self.assertEqual(plan["restore_images"], sorted([FRONT, BACK]))
        self.assertFalse(self.target_db.exists())
        self.assertFalse(self.target_images.exists())

    def test_existing_records_require_force(self):
        archive, _ = self.create()
        self.target_db.parent.mkdir(parents=True)
        db = Database(str(self.target_db))
        try:
            existing = db.create({"front_image_path": "/keep.jpg"})
        finally:
            db.close()
        with self.assertRaisesRegex(BackupError, "--force"):
            self.restore(archive)
        self.assertEqual([r["id"] for r in self.records(self.target_db)],
                         [existing["id"]])
        plan, _ = self.restore(archive, mode="replace", force=True)
        self.assertEqual(plan["imported"], 2)
        ids = sorted(r["id"] for r in self.records(self.target_db))
        self.assertEqual(ids, sorted([self.first["id"], self.second["id"]]))

    def test_append_mode_keeps_existing_records(self):
        archive, _ = self.create()
        self.target_db.parent.mkdir(parents=True)
        db = Database(str(self.target_db))
        try:
            db.create({"front_image_path": "/keep.jpg"})
        finally:
            db.close()
        plan, _ = self.restore(archive, mode="append", force=True)
        self.assertEqual(plan["imported"], 2)
        self.assertEqual(len(self.records(self.target_db)), 3)

    def test_conflicting_image_requires_force_and_identical_is_fine(self):
        archive, _ = self.create()
        self.target_images.mkdir(parents=True)
        (self.target_images / FRONT).write_bytes(PNG)      # identical content
        (self.target_images / BACK).write_bytes(JPEG)      # different content
        with self.assertRaisesRegex(BackupError, BACK):
            self.restore(archive)
        self.assertEqual((self.target_images / BACK).read_bytes(), JPEG)
        self.assertFalse(self.target_db.exists())
        plan, _ = self.restore(archive, force=True)
        self.assertEqual(plan["identical_images"], [FRONT])
        self.assertEqual(plan["conflicting_images"], [BACK])
        self.assertEqual((self.target_images / BACK).read_bytes(), PNG_BACK)

    def test_corrupt_archives_fail_before_any_mutation(self):
        archive, _ = self.create()
        corrupt = self.root / "corrupt.tar.gz"
        for payload in (b"not a tar archive", archive.read_bytes()[:200]):
            with self.subTest(payload=payload[:10]):
                corrupt.write_bytes(payload)
                with self.assertRaises(BackupError):
                    self.restore(corrupt)
                self.assertFalse(self.target_db.exists())
                self.assertFalse(self.target_images.exists())

    def test_tampered_image_checksum_is_rejected(self):
        archive, _ = self.create()
        tampered = self._rewrite(archive, replace={
            f"images/{FRONT}": b"\x89PNG\r\n\x1a\n" + b"tampered-content!"})
        with self.assertRaisesRegex(BackupError, "checksum"):
            self.restore(tampered)
        self.assertFalse(self.target_db.exists())

    def test_non_image_content_in_image_member_is_rejected(self):
        archive, _ = self.create()
        # Same size as the original, so the signature check (not the
        # size check) must reject the content.
        tampered = self._rewrite(archive, replace={
            f"images/{FRONT}": b"A" * len(PNG)})
        with self.assertRaisesRegex(BackupError, "does not match its extension"):
            self.restore(tampered)

    def test_path_traversal_and_unexpected_members_are_rejected(self):
        archive, _ = self.create()
        hostile_names = (
            "../outside.png",
            "images/../../outside.png",
            "/etc/passwd",
            "images/evil.txt",
            "images/" + "d" * 32 + ".svg",
            "extra.json",
        )
        for name in hostile_names:
            with self.subTest(name=name):
                hostile = self._rewrite(archive, add={name: b"hostile"})
                with self.assertRaisesRegex(BackupError,
                                            "unexpected archive member"):
                    self.restore(hostile)
                self.assertFalse(self.target_db.exists())
                self.assertFalse((self.root / "outside.png").exists())

    def test_symlink_and_directory_members_are_rejected(self):
        archive, _ = self.create()
        for make in (self._symlink_member, self._directory_member):
            with self.subTest(member=make.__name__):
                hostile = self._rewrite(archive, extra_member=make)
                with self.assertRaisesRegex(BackupError, "member"):
                    self.restore(hostile)

    def test_invalid_records_fail_before_any_mutation(self):
        archive, _ = self.create()
        with tarfile.open(archive, "r:gz") as tar:
            payload = json.loads(tar.extractfile("postcards.json").read())
        payload["postcards"][0]["unknown_field"] = "rejected"
        bad = self._rewrite(archive, replace={
            "postcards.json": json.dumps(payload).encode()})
        with self.assertRaisesRegex(BackupError, "failed validation"):
            self.restore(bad)
        self.assertFalse(self.target_db.exists())
        self.assertFalse(self.target_images.exists())

    def test_incompatible_versions_are_rejected(self):
        archive, _ = self.create()
        with tarfile.open(archive, "r:gz") as tar:
            manifest = json.loads(tar.extractfile("manifest.json").read())
            payload = json.loads(tar.extractfile("postcards.json").read())
        for field, value, message in (
            ("backup_version", BACKUP_VERSION + 1, "backup format version"),
            ("format", "something-else", "not a picture-postcard-manager"),
        ):
            with self.subTest(field=field):
                bad_manifest = dict(manifest, **{field: value})
                bad = self._rewrite(archive, replace={
                    "manifest.json": json.dumps(bad_manifest).encode()})
                with self.assertRaisesRegex(BackupError, message):
                    self.restore(bad)
        # A future schema version is rejected by the import validation.
        future = dict(manifest, schema_version=99)
        future_payload = dict(payload, schema_version=99)
        bad = self._rewrite(archive, replace={
            "manifest.json": json.dumps(future).encode(),
            "postcards.json": json.dumps(future_payload).encode()})
        with self.assertRaisesRegex(BackupError, "schema_version"):
            self.restore(bad)
        self.assertFalse(self.target_db.exists())

    def test_manifest_and_payload_must_agree(self):
        archive, _ = self.create()
        with tarfile.open(archive, "r:gz") as tar:
            manifest = json.loads(tar.extractfile("manifest.json").read())
        mismatch = dict(manifest, postcard_count=5)
        bad = self._rewrite(archive, replace={
            "manifest.json": json.dumps(mismatch).encode()})
        with self.assertRaisesRegex(BackupError, "postcard_count"):
            self.restore(bad)

    def test_interrupted_commit_never_leaves_partial_database(self):
        """The database replacement is the last step: a crash while placing
        images leaves the live database untouched."""
        archive, _ = self.create()
        original = os.replace
        calls = []

        def crash_on_image(src, dst):
            if Path(dst).name == FRONT or Path(dst).name == BACK:
                calls.append(dst)
                raise OSError("simulated crash")
            return original(src, dst)

        with patch("app.backup.os.replace", side_effect=crash_on_image):
            with self.assertRaises(OSError):
                self.restore(archive)
        self.assertTrue(calls)
        self.assertFalse(self.target_db.exists())
        # No partial temp files remain in the image directory.
        leftovers = [p.name for p in self.target_images.iterdir()
                     if p.name.startswith(".ppm-restore-")]
        self.assertEqual(leftovers, [])
        # The restore can simply be retried.
        plan, _ = self.restore(archive)
        self.assertEqual(plan["imported"], 2)

    def test_missing_archived_image_is_reported_in_preview(self):
        (self.image_dir / BACK).unlink()
        archive, _ = self.create()
        plan, output = self.restore(archive, dry_run=True)
        self.assertEqual(plan["missing_images"], [BACK])
        self.assertIn("not in the archive", output)

    # -- helpers ------------------------------------------------------------

    def _rewrite(self, archive, replace=None, add=None, extra_member=None):
        """Return a new archive with members replaced/added (test fixture)."""
        replace = replace or {}
        target = self.root / "rewritten.tar.gz"
        target.unlink(missing_ok=True)
        with tarfile.open(archive, "r:gz") as src, \
                tarfile.open(target, "w:gz") as dst:
            for member in src.getmembers():
                if member.name in replace:
                    data = replace[member.name]
                    info = tarfile.TarInfo(member.name)
                    info.size = len(data)
                    dst.addfile(info, io.BytesIO(data))
                else:
                    dst.addfile(member, src.extractfile(member))
            for name, data in (add or {}).items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                dst.addfile(info, io.BytesIO(data))
            if extra_member is not None:
                dst.addfile(extra_member())
        return target

    @staticmethod
    def _symlink_member():
        info = tarfile.TarInfo("images/" + "e" * 32 + ".png")
        info.type = tarfile.SYMTYPE
        info.linkname = "../../etc/passwd"
        return info

    @staticmethod
    def _directory_member():
        info = tarfile.TarInfo("images/nested")
        info.type = tarfile.DIRTYPE
        return info


class BackupCliTest(BackupFixture):
    def test_cli_create_and_restore_round_trip(self):
        archive = self.root / "cli-backup.tar.gz"
        main(["create", "--db", str(self.db_path),
              "--image-dir", str(self.image_dir), "--output", str(archive)])
        self.assertTrue(archive.is_file())
        main(["restore", str(archive), "--db", str(self.target_db),
              "--image-dir", str(self.target_images)])
        self.assertEqual(len(self.records(self.target_db)), 2)
        self.assertTrue((self.target_images / FRONT).is_file())

    def test_cli_dry_run_and_errors_exit_nonzero(self):
        archive = self.root / "cli-backup.tar.gz"
        main(["create", "--db", str(self.db_path),
              "--image-dir", str(self.image_dir), "--output", str(archive)])
        main(["restore", str(archive), "--dry-run",
              "--db", str(self.target_db),
              "--image-dir", str(self.target_images)])
        self.assertFalse(self.target_db.exists())
        with self.assertRaises(SystemExit) as caught:
            main(["restore", str(self.root / "missing.tar.gz"),
                  "--db", str(self.target_db),
                  "--image-dir", str(self.target_images)])
        self.assertEqual(caught.exception.code, 1)

    def test_cli_defaults_image_dir_next_to_database(self):
        archive = self.root / "cli-default.tar.gz"
        main(["create", "--db", str(self.db_path), "--output", str(archive)])
        with tarfile.open(archive, "r:gz") as tar:
            self.assertIn(f"images/{FRONT}", tar.getnames())


if __name__ == "__main__":
    unittest.main()
