import json
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

# The exact table shape of a real schema-5 database (as created by the
# previous release), including the AUTOINCREMENT sequence and uuid index.
V5_SCHEMA = """
CREATE TABLE postcards (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid        TEXT NOT NULL,
    front_image_path TEXT NOT NULL DEFAULT '',
    back_image_path TEXT NOT NULL DEFAULT '',
    place       TEXT NOT NULL DEFAULT '',
    region      TEXT NOT NULL DEFAULT '',
    year        TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    tags        TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX postcards_uuid ON postcards(uuid);
PRAGMA user_version = 5;
"""


def make_v5_db(path, rows):
    """Create a real-shape schema-5 database with (id, place, region, tags) rows."""
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.executescript(V5_SCHEMA)
        for pid, place, region, tags in rows:
            conn.execute(
                "INSERT INTO postcards (id, uuid, front_image_path, place, region,"
                " year, tags, created_at, updated_at)"
                " VALUES (?, ?, '/front.jpg', ?, ?, '1910', ?, ?, ?)",
                (pid, f"b962a358-8899-4000-8999-6973bac5d{pid:03d}", place, region,
                 json.dumps(tags, ensure_ascii=False), f"c{pid}", f"u{pid}"),
            )


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
                for field in ("title", "notes", "place", "region"):
                    self.assertNotIn(field, legacy)
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
        """Title, then notes, then description, verbatim with single blank-line joins."""
        cases = (
            (("", "", ""), ""),
            (("", "", "Desc"), "Desc"),
            (("Title", "", ""), "Title"),
            (("", "Notes", ""), "Notes"),
            (("Title", "Notes", ""), "Title\n\nNotes"),
            (("Title", "", "Desc"), "Title\n\nDesc"),
            (("", "Notes", "Desc"), "Notes\n\nDesc"),
            (("Title", "Notes", "Desc"), "Title\n\nNotes\n\nDesc"),
            # Whitespace-only values are skipped.
            ((" \n ", "\t", "Desc"), "Desc"),
            # Existing newlines at joins count towards the blank line; nothing
            # is duplicated and the payload is not trimmed (trailing newlines
            # of the last piece are kept).
            (("Title\n", "\nNotes", "Desc\n\n"), "Title\n\nNotes\n\nDesc\n\n"),
            (("Title\n\n", "Notes", ""), "Title\n\nNotes"),
            (("Title", "\n\n\nNotes", ""), "Title\n\n\nNotes"),
            # Non-newline whitespace is preserved verbatim (lossless).
            ((" Title ", "", "\tDesc "), " Title \n\n\tDesc "),
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
            # The migration is lossless: surrounding whitespace of non-empty
            # values is preserved and existing newlines at joins are reused.
            (6, " Padded ", "Notes\n", "\nDesc ", " Padded \n\nNotes\n\nDesc "),
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

    def test_legacy_migration_rebuilds_table_without_drop_column(self):
        """The schema-5 migration uses the table rebuild on every SQLite version.

        ``ALTER TABLE ... DROP COLUMN`` requires SQLite >= 3.35, so the
        migration must never emit it. The rebuild must preserve ids, uuids,
        timestamps, tags and all data, recreate the uuid index, and keep the
        AUTOINCREMENT sequence so deleted ids are not reused.
        """
        class NoDropColumnConnection(sqlite3.Connection):
            def execute(self, sql, parameters=()):
                if "DROP COLUMN" in sql.upper():
                    raise AssertionError(f"DROP COLUMN must not be used: {sql}")
                return super().execute(sql, parameters)

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
                conn.execute(
                    "INSERT INTO postcards (id, uuid, title, notes, front_image_path, place,"
                    " tags, created_at, updated_at) VALUES (7, 'b962a358-8899-4000-8999-"
                    "6973bac5d597', 'T', 'N', '/front.jpg', 'Wien', '[\"alt\"]', 'c7', 'u7')"
                )
                conn.execute(
                    "INSERT INTO postcards (id, uuid, front_image_path, created_at, updated_at)"
                    " VALUES (9, 'b962a358-8899-4000-8999-6973bac5d599', '/f.jpg', 'c9', 'u9')"
                )
                conn.execute("DELETE FROM postcards WHERE id = 9")

            real_connect = sqlite3.connect

            def connect(*args, **kwargs):
                kwargs["factory"] = NoDropColumnConnection
                return real_connect(*args, **kwargs)

            with patch("app.db.sqlite3.connect", side_effect=connect):
                db = Database(path)
                self.addCleanup(db.close)
                record = db.get(7)
                self.assertEqual(record["description"], "T\n\nN")
                self.assertEqual(record["uuid"], "b962a358-8899-4000-8999-6973bac5d597")
                # The legacy place value is migrated into the tags.
                self.assertEqual(record["tags"], ["alt", "Wien"])
                self.assertNotIn("place", record)
                self.assertEqual(record["created_at"], "c7")
                self.assertEqual(record["updated_at"], "u7")
                # Deleted ids are not reused after the rebuild.
                self.assertGreater(db.create({"front_image_path": "/new.jpg"})["id"], 9)
            with closing(sqlite3.connect(path)) as conn, conn:
                columns = [row[1] for row in conn.execute("PRAGMA table_info(postcards)")]
                self.assertNotIn("title", columns)
                self.assertNotIn("notes", columns)
                # The unique uuid index survives the rebuild.
                self.assertIsNotNone(conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'index'"
                    " AND name = 'postcards_uuid'"
                ).fetchone())
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(
                        "INSERT INTO postcards (uuid, front_image_path, created_at, updated_at)"
                        " VALUES ('b962a358-8899-4000-8999-6973bac5d597', '/x.jpg', 'c', 'u')"
                    )

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
        self.assertEqual(db.update(item["id"], {"year": "1910"})["front_image_path"], "/front.jpg")


class LocationMigrationTest(unittest.TestCase):
    """Schema 6: place/region values move into tags via a table rebuild."""

    def migrate(self, rows):
        """Run the schema-6 migration against a real-shape schema-5 database."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name) / "v5.db"
        make_v5_db(path, rows)
        db = Database(path)
        self.addCleanup(db.close)
        return db, path

    def test_values_become_deduplicated_tags(self):
        db, path = self.migrate([
            # place and region are appended after existing tags, place first.
            (1, "Wien", "Niederösterreich", ["Donau"]),
            # A value already present as a tag is not duplicated.
            (2, "Linz", "Oberösterreich", ["Oberösterreich", "Stadt"]),
            # Equal place and region produce a single tag.
            (3, "Salzburg", "Salzburg", []),
            # Tags are case-sensitive: a case variant stays a separate tag.
            (4, "wien", "", ["Wien"]),
            # Blank and whitespace-only values do not create tags.
            (5, "", "   \t\n", ["Keep"]),
            # Surrounding whitespace is trimmed; inner text is verbatim.
            (6, "  Zell am See ", "", []),
            # Unicode values are preserved exactly.
            (7, "Großglockner ✉", "Kärnten", ["Üni ✉"]),
        ])
        expected = {
            1: ["Donau", "Wien", "Niederösterreich"],
            2: ["Oberösterreich", "Stadt", "Linz"],
            3: ["Salzburg"],
            4: ["Wien", "wien"],
            5: ["Keep"],
            6: ["Zell am See"],
            7: ["Üni ✉", "Großglockner ✉", "Kärnten"],
        }
        for pid, tags in expected.items():
            with self.subTest(id=pid):
                record = db.get(pid)
                self.assertEqual(record["tags"], tags)
                self.assertNotIn("place", record)
                self.assertNotIn("region", record)
                # Everything else is preserved.
                self.assertEqual(record["year"], "1910")
                self.assertEqual(record["created_at"], f"c{pid}")
                self.assertEqual(record["updated_at"], f"u{pid}")
                self.assertEqual(
                    record["uuid"], f"b962a358-8899-4000-8999-6973bac5d{pid:03d}")
        # Migrated values are searchable and tag-filterable.
        self.assertEqual([p["id"] for p in db.list("Zell am")], [6])
        self.assertEqual([p["id"] for p in db.list(filters={"tag": "Wien"})],
                         [4, 1])
        self.assertNotIn("place", db.filter_values())
        with closing(sqlite3.connect(path)) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0],
                             SCHEMA_VERSION)
            columns = [row[1] for row in conn.execute("PRAGMA table_info(postcards)")]
            self.assertNotIn("place", columns)
            self.assertNotIn("region", columns)
            # The unique uuid index survives the rebuild.
            self.assertIsNotNone(conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
                " AND name = 'postcards_uuid'").fetchone())

    def test_rebuild_preserves_autoincrement_sequence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v5.db"
            make_v5_db(path, [(3, "Wien", "", []), (9, "Graz", "", [])])
            with closing(sqlite3.connect(path)) as conn, conn:
                conn.execute("DELETE FROM postcards WHERE id = 9")
            db = Database(path)
            self.addCleanup(db.close)
            # Deleted ids are not reused after the rebuild.
            self.assertGreater(db.create({"front_image_path": "/new.jpg"})["id"], 9)

    def test_migration_never_uses_drop_column(self):
        class NoDropColumnConnection(sqlite3.Connection):
            def execute(self, sql, parameters=()):
                if "DROP COLUMN" in sql.upper():
                    raise AssertionError(f"DROP COLUMN must not be used: {sql}")
                return super().execute(sql, parameters)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v5.db"
            make_v5_db(path, [(1, "Wien", "Wien", ["a"])])
            real_connect = sqlite3.connect

            def connect(*args, **kwargs):
                kwargs["factory"] = NoDropColumnConnection
                return real_connect(*args, **kwargs)

            with patch("app.db.sqlite3.connect", side_effect=connect):
                db = Database(path)
                self.addCleanup(db.close)
                self.assertEqual(db.get(1)["tags"], ["a", "Wien"])

    def test_migration_is_idempotent_on_reopen(self):
        db, path = self.migrate([(1, "Wien", "Tirol", ["x"])])
        first = db.get(1)
        db.close()
        reopened = Database(path)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.get(1), first)
        self.assertEqual(reopened.get(1)["tags"], ["x", "Wien", "Tirol"])

    def test_failed_location_migration_rolls_back(self):
        """A failure during the rebuild leaves the schema-5 database intact."""
        class FailingConnection(sqlite3.Connection):
            def execute(self, sql, parameters=()):
                if sql.startswith("ALTER TABLE postcards_migrated RENAME"):
                    raise sqlite3.OperationalError("simulated migration failure")
                return super().execute(sql, parameters)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v5.db"
            make_v5_db(path, [(1, "Wien", "Tirol", ["keep"])])
            failing = sqlite3.connect(path, factory=FailingConnection)
            with patch("app.db.sqlite3.connect", return_value=failing):
                with self.assertRaisesRegex(sqlite3.OperationalError,
                                            "simulated migration failure"):
                    Database(path)
            with closing(sqlite3.connect(path)) as conn:
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 5)
                columns = [row[1] for row in conn.execute("PRAGMA table_info(postcards)")]
                self.assertIn("place", columns)
                self.assertIn("region", columns)
                row = conn.execute(
                    "SELECT place, region, tags FROM postcards WHERE id = 1").fetchone()
                self.assertEqual(row, ("Wien", "Tirol", '["keep"]'))


if __name__ == "__main__":
    unittest.main()
