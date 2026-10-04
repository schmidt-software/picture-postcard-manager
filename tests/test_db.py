import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from app.db import Database, POSTCARD_FIELDS, SCHEMA_VERSION


LEGACY_SCHEMA = """
CREATE TABLE postcards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX postcards_title ON postcards(title);
"""


class DatabaseTest(unittest.TestCase):
    def test_migration_preserves_existing_database(self):
        for version in (0, 1):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "legacy.db"
                with closing(sqlite3.connect(path)) as conn, conn:
                    conn.executescript(LEGACY_SCHEMA)
                    conn.execute(f"PRAGMA user_version = {version}")
                    conn.execute(
                        "INSERT INTO postcards VALUES (?, ?, ?, ?, ?)",
                        (17, "Legacy title", "Legacy notes", "created", "updated"),
                    )
                    conn.execute(
                        "INSERT INTO postcards VALUES (?, ?, ?, ?, ?)",
                        (50, "Deleted", "", "created", "updated"),
                    )
                    conn.execute("DELETE FROM postcards WHERE id = 50")
                    conn.execute("CREATE TABLE unrelated (value TEXT)")
                    conn.execute("INSERT INTO unrelated VALUES ('keep me')")

                db = Database(path)
                self.addCleanup(db.close)
                legacy = db.get(17)
                self.assertEqual(
                    {key: legacy[key] for key in ("id", "title", "notes", "created_at", "updated_at")},
                    {"id": 17, "title": "Legacy title", "notes": "Legacy notes",
                     "created_at": "created", "updated_at": "updated"},
                )
                for field in POSTCARD_FIELDS:
                    self.assertEqual(legacy[field], "")
                self.assertEqual(legacy["tags"], [])
                with closing(sqlite3.connect(path)) as conn, conn:
                    self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
                    self.assertEqual(conn.execute("SELECT value FROM unrelated").fetchone()[0], "keep me")
                    self.assertIsNotNone(conn.execute(
                        "SELECT name FROM sqlite_master WHERE name = 'postcards_title'"
                    ).fetchone())
                with self.assertRaisesRegex(ValueError, "front_image_path"):
                    db.update(17, {"description": "Needs image"})
                self.assertEqual(db.get(17), legacy)
                export = db.export_data()
                self.assertEqual(db.import_data(export, "replace"), 1)
                self.assertEqual(db.get(17), legacy)
                reopened = Database(path)
                self.addCleanup(reopened.close)
                self.assertEqual(reopened.get(17), legacy)
                self.assertGreater(reopened.create({"front_image_path": "/front.jpg"})["id"], 50)

    def test_failed_migration_rolls_back_all_schema_changes(self):
        class FailingConnection(sqlite3.Connection):
            def execute(self, sql, parameters=()):
                if sql.startswith("ALTER TABLE postcards ADD COLUMN back_image_path"):
                    raise sqlite3.OperationalError("simulated migration failure")
                return super().execute(sql, parameters)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.db"
            with closing(sqlite3.connect(path)) as conn, conn:
                conn.executescript(LEGACY_SCHEMA)
                conn.execute("PRAGMA user_version = 1")
                conn.execute(
                    "INSERT INTO postcards VALUES (1, 'Legacy', 'Keep', 'created', 'updated')"
                )
            failing = sqlite3.connect(path, factory=FailingConnection)
            with patch("app.db.sqlite3.connect", return_value=failing):
                with self.assertRaisesRegex(sqlite3.OperationalError, "simulated migration failure"):
                    Database(path)
            with closing(sqlite3.connect(path)) as conn, conn:
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 1)
                self.assertNotIn(
                    "front_image_path",
                    [row[1] for row in conn.execute("PRAGMA table_info(postcards)")],
                )
                self.assertEqual(conn.execute("SELECT * FROM postcards").fetchone(),
                                 (1, "Legacy", "Keep", "created", "updated"))

    def test_newer_schema_is_not_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "future.db"
            with closing(sqlite3.connect(path)) as conn, conn:
                conn.executescript(LEGACY_SCHEMA)
                conn.execute("PRAGMA user_version = 99")
            with self.assertRaisesRegex(ValueError, "unsupported database schema"):
                Database(path)
            with closing(sqlite3.connect(path)) as conn, conn:
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 99)
                columns = [row[1] for row in conn.execute("PRAGMA table_info(postcards)")]
                self.assertNotIn("front_image_path", columns)

    def test_database_validates_required_path(self):
        db = Database(":memory:")
        self.addCleanup(db.close)
        with self.assertRaisesRegex(ValueError, "front_image_path"):
            db.create({})
        item = db.create({"front_image_path": "/front.jpg"})
        with self.assertRaisesRegex(ValueError, "front_image_path"):
            db.update(item["id"], {"front_image_path": None})
        self.assertEqual(db.get(item["id"]), item)
        self.assertEqual(db.update(item["id"], {"place": "Berlin"})["front_image_path"], "/front.jpg")


if __name__ == "__main__":
    unittest.main()
