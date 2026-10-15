import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from app.db import Database, POSTCARD_FIELDS, SCHEMA_VERSION, merge_legacy_fields


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
                    {key: legacy[key] for key in ("id", "description", "created_at", "updated_at")},
                    {"id": 17, "description": "Legacy title\n\nLegacy notes",
                     "created_at": "created", "updated_at": "updated"},
                )
                self.assertNotIn("title", legacy)
                self.assertNotIn("notes", legacy)
                for field in POSTCARD_FIELDS:
                    if field != "description":
                        self.assertEqual(legacy[field], "")
                self.assertEqual(legacy["tags"], [])
                with closing(sqlite3.connect(path)) as conn, conn:
                    self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
                    self.assertEqual(conn.execute("SELECT value FROM unrelated").fetchone()[0], "keep me")
                    # The index on the dropped title column is removed with the column.
                    self.assertIsNone(conn.execute(
                        "SELECT name FROM sqlite_master WHERE name = 'postcards_title'"
                    ).fetchone())
                    columns = [row[1] for row in conn.execute("PRAGMA table_info(postcards)")]
                    self.assertNotIn("title", columns)
                    self.assertNotIn("notes", columns)
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

    def test_legacy_merge_format(self):
        """Title, then notes, then description, joined by single blank lines."""
        cases = (
            (("", "", ""), ""),
            (("", "", "Desc"), "Desc"),
            (("Title", "", ""), "Title"),
            (("", "Notes", ""), "Notes"),
            (("Title", "Notes", ""), "Title\n\nNotes"),
            (("Title", "", "Desc"), "Title\n\nDesc"),
            (("", "Notes", "Desc"), "Notes\n\nDesc"),
            (("Title", "Notes", "Desc"), "Title\n\nNotes\n\nDesc"),
            # Whitespace-only values are skipped; no duplicate blank lines.
            ((" \n ", "\t", "Desc"), "Desc"),
            (("Title\n", "\nNotes", "Desc\n\n"), "Title\n\nNotes\n\nDesc"),
            # Internal line breaks are preserved.
            (("Title", "Line 1\nLine 2", ""), "Title\n\nLine 1\nLine 2"),
        )
        for (title, notes, description), expected in cases:
            with self.subTest(title=title, notes=notes, description=description):
                self.assertEqual(merge_legacy_fields(title, notes, description), expected)

    def test_v4_migration_merges_title_and_notes_into_description(self):
        rows = (
            (1, "Berlin", "Souvenir", "Street view", "Berlin\n\nSouvenir\n\nStreet view"),
            (2, "Only title", "", "", "Only title"),
            (3, "", "Only notes", "Desc", "Only notes\n\nDesc"),
            (4, "", "", "Untouched", "Untouched"),
            (5, "  ", " \n", "Whitespace legacy", "Whitespace legacy"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v4.db"
            with closing(sqlite3.connect(path)) as conn, conn:
                conn.executescript("""
                    CREATE TABLE postcards (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        uuid TEXT NOT NULL,
                        title TEXT NOT NULL DEFAULT '',
                        notes TEXT NOT NULL DEFAULT '',
                        front_image_path TEXT NOT NULL DEFAULT '',
                        back_image_path TEXT NOT NULL DEFAULT '',
                        place TEXT NOT NULL DEFAULT '',
                        region TEXT NOT NULL DEFAULT '',
                        year TEXT NOT NULL DEFAULT '',
                        description TEXT NOT NULL DEFAULT '',
                        tags TEXT NOT NULL DEFAULT '[]',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE UNIQUE INDEX postcards_uuid ON postcards(uuid);
                    PRAGMA user_version = 4;
                """)
                for pid, title, notes, description, _ in rows:
                    conn.execute(
                        "INSERT INTO postcards (id, uuid, title, notes, front_image_path,"
                        " description, created_at, updated_at)"
                        " VALUES (?, ?, ?, ?, '/front.jpg', ?, 'c', 'u')",
                        (pid, f"b962a358-8899-4000-8999-6973bac5d59{pid}", title, notes, description),
                    )
            db = Database(path)
            self.addCleanup(db.close)
            for pid, _, _, _, expected in rows:
                with self.subTest(id=pid):
                    record = db.get(pid)
                    self.assertEqual(record["description"], expected)
                    self.assertNotIn("title", record)
                    self.assertNotIn("notes", record)
            self.assertEqual(db.get(1)["updated_at"], "u")
            with closing(sqlite3.connect(path)) as conn, conn:
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
                columns = [row[1] for row in conn.execute("PRAGMA table_info(postcards)")]
                self.assertNotIn("title", columns)
                self.assertNotIn("notes", columns)

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
