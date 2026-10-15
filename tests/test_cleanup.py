"""Tests for the orphaned-image cleanup command."""

import io
import tempfile
import unittest
from pathlib import Path

from app.cleanup import cleanup, find_orphans, main, referenced_names
from app.db import Database

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 8
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
