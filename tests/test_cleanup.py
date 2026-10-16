"""Tests for the orphaned-image cleanup command."""

import io
import os
import tempfile
import unittest
from pathlib import Path

from app.cleanup import cleanup, find_orphans, main, referenced_names
from app.db import Database
from app import thumbs

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 8
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 8
GENERATED_A = "a" * 32 + ".png"
GENERATED_B = "b" * 32 + ".jpg"
GENERATED_C = "c" * 32 + ".webp"


class CleanupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "postcards.db"
        self.image_dir = self.root / "images"
        self.image_dir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def add_postcard(self, front, back=""):
        db = Database(str(self.db_path))
        try:
            db.create({"front_image_path": front, "back_image_path": back})
        finally:
            db.close()

    def run_cleanup(self, delete=False):
        out = io.StringIO()
        orphans = cleanup(str(self.db_path), self.image_dir, delete=delete, out=out)
        return orphans, out.getvalue()

    def test_referenced_names_accepts_url_and_filesystem_paths(self):
        postcards = [
            {"front_image_path": f"/images/{GENERATED_A}", "back_image_path": ""},
            {"front_image_path": f"C:\\scans\\{GENERATED_B}",
             "back_image_path": f"local/dir/{GENERATED_C}"},
            {"front_image_path": "manual/path.png", "back_image_path": None},
        ]
        self.assertEqual(referenced_names(postcards),
                         {GENERATED_A, GENERATED_B, GENERATED_C})

    def test_referenced_names_ignores_query_fragment_and_url_forms(self):
        postcards = [
            {"front_image_path": f"/images/{GENERATED_A}?v=1", "back_image_path": ""},
            {"front_image_path": f"/images/{GENERATED_B}#frag", "back_image_path": ""},
            {"front_image_path": f"http://localhost:8000/images/{GENERATED_C}?v=2#top",
             "back_image_path": ""},
        ]
        self.assertEqual(referenced_names(postcards),
                         {GENERATED_A, GENERATED_B, GENERATED_C})

    def test_referenced_names_handles_percent_encoding(self):
        encoded = "/images/" + GENERATED_A.replace(".png", "%2epng")
        postcards = [{"front_image_path": encoded, "back_image_path": ""}]
        self.assertEqual(referenced_names(postcards), {GENERATED_A})

    def test_files_referenced_with_query_or_fragment_are_never_deleted(self):
        (self.image_dir / GENERATED_A).write_bytes(PNG)
        (self.image_dir / GENERATED_B).write_bytes(PNG)
        (self.image_dir / GENERATED_C).write_bytes(PNG)
        self.add_postcard(f"/images/{GENERATED_A}?v=1",
                          back=f"/images/{GENERATED_B}#frag")
        self.add_postcard(f"http://localhost:8000/images/{GENERATED_C}?v=2")
        orphans, _ = self.run_cleanup(delete=True)
        self.assertEqual(orphans, [])
        for name in (GENERATED_A, GENERATED_B, GENERATED_C):
            self.assertTrue((self.image_dir / name).exists())

    def test_orphans_are_listed_but_kept_without_delete(self):
        (self.image_dir / GENERATED_A).write_bytes(PNG)
        (self.image_dir / GENERATED_B).write_bytes(PNG)
        self.add_postcard(f"/images/{GENERATED_A}")
        orphans, output = self.run_cleanup()
        self.assertEqual([p.name for p in orphans], [GENERATED_B])
        self.assertIn(GENERATED_B, output)
        self.assertIn("--delete", output)
        self.assertTrue((self.image_dir / GENERATED_A).exists())
        self.assertTrue((self.image_dir / GENERATED_B).exists())

    def test_delete_removes_only_unreferenced_generated_files(self):
        (self.image_dir / GENERATED_A).write_bytes(PNG)
        (self.image_dir / GENERATED_B).write_bytes(PNG)
        manual = self.image_dir / "manual-scan.png"
        manual.write_bytes(PNG)
        self.add_postcard(f"/images/{GENERATED_A}", back=f"/images/{GENERATED_A}")
        orphans, output = self.run_cleanup(delete=True)
        self.assertEqual([p.name for p in orphans], [GENERATED_B])
        self.assertIn("Deleted", output)
        self.assertTrue((self.image_dir / GENERATED_A).exists())
        self.assertFalse((self.image_dir / GENERATED_B).exists())
        self.assertTrue(manual.exists())

    def test_non_generated_and_nested_files_are_ignored(self):
        (self.image_dir / "notes.txt").write_text("keep")
        nested = self.image_dir / "sub"
        nested.mkdir()
        (nested / GENERATED_A).write_bytes(PNG)
        self.add_postcard("/front.jpg")
        orphans, _ = self.run_cleanup(delete=True)
        self.assertEqual(orphans, [])
        self.assertTrue((self.image_dir / "notes.txt").exists())
        self.assertTrue((nested / GENERATED_A).exists())

    def test_symlinks_are_never_deleted(self):
        target = self.root / "outside.png"
        target.write_bytes(PNG)
        link = self.image_dir / GENERATED_B
        link.symlink_to(target)
        self.add_postcard("/front.jpg")
        orphans, _ = self.run_cleanup(delete=True)
        self.assertEqual(orphans, [])
        self.assertTrue(link.is_symlink())
        self.assertTrue(target.exists())

    def test_find_orphans_with_missing_image_dir(self):
        self.assertEqual(find_orphans(self.root / "missing", []), [])

    def test_empty_collection_marks_all_generated_files_as_orphans(self):
        (self.image_dir / GENERATED_A).write_bytes(PNG)
        Database(str(self.db_path)).close()
        orphans, _ = self.run_cleanup()
        self.assertEqual([p.name for p in orphans], [GENERATED_A])

    def test_main_requires_existing_database(self):
        with self.assertRaises(SystemExit):
            main(["--db", str(self.root / "missing.db")])

    def test_main_dry_run_defaults_to_images_next_to_database(self):
        (self.image_dir / GENERATED_A).write_bytes(PNG)
        Database(str(self.db_path)).close()
        main(["--db", str(self.db_path)])
        self.assertTrue((self.image_dir / GENERATED_A).exists())


if __name__ == "__main__":
    unittest.main()


class CleanupThumbTest(unittest.TestCase):
    """The cleanup CLI follows originals: referenced thumbs stay, others go."""

    REFERENCED = GENERATED_A
    ORPHANED = GENERATED_B
    VANISHED = GENERATED_C

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.image_dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.thumb_dir = self.image_dir / thumbs.DIR_NAME
        self.thumb_dir.mkdir()
        (self.image_dir / self.REFERENCED).write_bytes(PNG)
        (self.image_dir / self.ORPHANED).write_bytes(JPEG)
        self.postcards = [{"front_image_path": f"/images/{self.REFERENCED}",
                           "back_image_path": ""}]

    def thumb_of(self, name, extension="jpg"):
        path = self.thumb_dir / f"{name.rsplit('.', 1)[0]}.{thumbs.THUMB_SIZE}.{extension}"
        path.write_bytes(JPEG if extension == "jpg" else PNG)
        return path

    def test_thumbs_follow_their_originals(self):
        kept = self.thumb_of(self.REFERENCED)
        kept_png = self.thumb_of(self.REFERENCED, "png")
        orphan_thumb = self.thumb_of(self.ORPHANED)
        vanished_thumb = self.thumb_of(self.VANISHED)
        stray = self.thumb_dir / "notes.txt"
        stray.write_text("manual file")
        orphans = find_orphans(self.image_dir, self.postcards)
        self.assertEqual(orphans, sorted([self.image_dir / self.ORPHANED,
                                          orphan_thumb, vanished_thumb]))
        self.assertNotIn(kept, orphans)
        self.assertNotIn(kept_png, orphans)
        self.assertNotIn(stray, orphans)

    def test_symlinked_thumbs_are_ignored(self):
        target = self.image_dir / "outside.jpg"
        target.write_bytes(JPEG)
        link = self.thumb_dir / f"{'d' * 32}.{thumbs.THUMB_SIZE}.jpg"
        os.symlink(target, link)
        self.assertEqual(find_orphans(self.image_dir, self.postcards),
                         [self.image_dir / self.ORPHANED])

    def test_missing_thumbs_directory_is_fine(self):
        self.thumb_dir.rmdir()
        self.assertEqual(find_orphans(self.image_dir, self.postcards),
                         [self.image_dir / self.ORPHANED])
