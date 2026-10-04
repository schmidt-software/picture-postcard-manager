"""SQLite persistence layer for postcards."""

import json
import sqlite3
import threading
from datetime import datetime, timezone
from uuid import UUID, uuid4

SCHEMA_VERSION = 4
IMPORT_VERSIONS = (1, 2, 3, 4)

POSTCARD_FIELDS = (
    "front_image_path", "back_image_path", "place", "region", "year", "description",
)
TEXT_FIELDS = ("title", "notes", *POSTCARD_FIELDS)
EDITABLE_FIELDS = (*TEXT_FIELDS, "tags")
RECORD_FIELDS = (*EDITABLE_FIELDS, "id", "uuid", "created_at", "updated_at")

SCHEMA = """
CREATE TABLE IF NOT EXISTS postcards (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid        TEXT NOT NULL,
    title       TEXT NOT NULL DEFAULT '',
    notes       TEXT NOT NULL DEFAULT '',
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
"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        try:
            with self._lock, self._conn:
                version = self._conn.execute("PRAGMA user_version").fetchone()[0]
                if version > SCHEMA_VERSION:
                    raise ValueError(f"unsupported database schema version: {version}")
                self._conn.execute("BEGIN")
                self._conn.execute(SCHEMA)
                columns = {
                    row["name"] for row in self._conn.execute("PRAGMA table_info(postcards)")
                }
                for field in POSTCARD_FIELDS:
                    if field not in columns:
                        self._conn.execute(
                            f"ALTER TABLE postcards ADD COLUMN {field} TEXT NOT NULL DEFAULT ''"
                        )
                if "tags" not in columns:
                    self._conn.execute(
                        "ALTER TABLE postcards ADD COLUMN tags TEXT NOT NULL DEFAULT '[]'"
                    )
                if "uuid" not in columns:
                    self._conn.execute("ALTER TABLE postcards ADD COLUMN uuid TEXT NOT NULL DEFAULT ''")
                    for row in self._conn.execute("SELECT id FROM postcards").fetchall():
                        self._conn.execute(
                            "UPDATE postcards SET uuid = ? WHERE id = ?",
                            (str(uuid4()), row["id"]),
                        )
                self._conn.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS postcards_uuid ON postcards(uuid)"
                )
                self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        except (sqlite3.Error, ValueError):
            self._conn.close()
            raise

    def close(self):
        self._conn.close()

    @staticmethod
    def _clean(data):
        if not isinstance(data, dict):
            raise ValueError("postcard must be an object")
        unknown = set(data) - set(RECORD_FIELDS)
        if unknown:
            raise ValueError(f"unknown postcard fields: {', '.join(sorted(unknown))}")
        fields = {}
        for key in EDITABLE_FIELDS:
            if key not in data:
                continue
            value = data[key]
            if key == "tags":
                value = json.dumps(Database._clean_tags(value), ensure_ascii=False)
            elif key == "front_image_path":
                Database._validate_front(value)
            elif value is None:
                value = ""
            elif key == "year" and type(value) is int:
                value = str(value)
            elif not isinstance(value, str):
                raise ValueError(f"{key} must be a string or null")
            fields[key] = value
        return fields

    @staticmethod
    def _clean_tags(value):
        """Trim tags and drop exact duplicates (case-sensitive), keeping first-seen order."""
        if not isinstance(value, list):
            raise ValueError("tags must be an array of strings")
        tags = []
        for tag in value:
            if not isinstance(tag, str):
                raise ValueError("tags must be an array of strings")
            tag = tag.strip()
            if not tag:
                raise ValueError("tags must not be blank")
            if tag not in tags:
                tags.append(tag)
        return tags

    @staticmethod
    def _row(row):
        record = dict(row)
        record["tags"] = json.loads(record["tags"])
        return record

    @staticmethod
    def _validate_front(value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("front_image_path is required and must be a non-empty string")

    @staticmethod
    def _validate_uuid(value):
        try:
            parsed = UUID(value) if isinstance(value, str) else None
        except ValueError:
            parsed = None
        if parsed is None or parsed.version != 4 or str(parsed) != value:
            raise ValueError("uuid must be a canonical lowercase UUIDv4")
        return value

    def list(self, query=None):
        sql = "SELECT * FROM postcards"
        params = ()
        if query:
            # Tags are matched as decoded text, not as their JSON representation.
            sql += " WHERE " + " OR ".join(
                [f"{field} LIKE ?" for field in TEXT_FIELDS]
                + ["EXISTS (SELECT 1 FROM json_each(postcards.tags) WHERE value LIKE ?)"]
            )
            params = (f"%{query}%",) * (len(TEXT_FIELDS) + 1)
        sql += " ORDER BY id DESC"
        with self._lock:
            return [self._row(r) for r in self._conn.execute(sql, params)]

    def get(self, postcard_id):
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM postcards WHERE id = ?", (postcard_id,)
            ).fetchone()
        return self._row(row) if row else None

    def get_by_uuid(self, value):
        self._validate_uuid(value)
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM postcards WHERE uuid = ?", (value,)
            ).fetchone()
        return self._row(row) if row else None

    def _insert(self, data, keep_id=False, allow_legacy=False):
        fields = self._clean(data)
        if "uuid" in data:
            self._validate_uuid(data["uuid"])
        fields["uuid"] = data["uuid"] if keep_id and "uuid" in data else str(uuid4())
        if not allow_legacy or "front_image_path" in data:
            self._validate_front(fields.get("front_image_path"))
        for key in ("created_at", "updated_at"):
            if key in data and (
                not isinstance(data[key], str) or not data[key].strip()
            ):
                raise ValueError(f"{key} must be a non-empty string")
        fields["created_at"] = data.get("created_at") or _now()
        fields["updated_at"] = data.get("updated_at") or fields["created_at"]
        if "id" in data and (
            type(data["id"]) is not int or not 0 < data["id"] <= 2**63 - 1
        ):
            raise ValueError("id must be a positive SQLite integer (at most 9223372036854775807)")
        if keep_id and "id" in data:
            fields["id"] = data["id"]
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        cur = self._conn.execute(
            f"INSERT INTO postcards ({cols}) VALUES ({marks})", tuple(fields.values())
        )
        return cur.lastrowid

    def create(self, data):
        if isinstance(data, dict) and "uuid" in data:
            raise ValueError("uuid is generated by the server and cannot be changed")
        with self._lock, self._conn:
            new_id = self._insert(data)
        return self.get(new_id)

    def update(self, postcard_id, data):
        if isinstance(data, dict) and "uuid" in data:
            raise ValueError("uuid is generated by the server and cannot be changed")
        fields = self._clean(data)
        with self._lock, self._conn:
            existing = self._conn.execute(
                "SELECT * FROM postcards WHERE id = ?", (postcard_id,)
            ).fetchone()
            if existing is None:
                return None
            self._validate_front(fields.get("front_image_path", existing["front_image_path"]))
            fields["updated_at"] = _now()
            assignments = ", ".join(f"{k} = ?" for k in fields)
            self._conn.execute(
                f"UPDATE postcards SET {assignments} WHERE id = ?",
                (*fields.values(), postcard_id),
            )
        return self.get(postcard_id)

    def delete(self, postcard_id):
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM postcards WHERE id = ?", (postcard_id,))
        return cur.rowcount > 0

    def export_data(self):
        return {
            "format": "picture-postcard-manager",
            "schema_version": SCHEMA_VERSION,
            "exported_at": _now(),
            "postcards": self.list(),
        }

    def import_data(self, payload, mode="append"):
        """Import postcards from an export payload.

        mode "append" adds all entries with new ids,
        mode "replace" deletes all existing entries and keeps the original ids.
        The import runs in a single transaction.
        Version-1 exports may contain legacy entries without image paths.
        Such entries must receive a front image path before they can be edited.
        Versions 1-3 are accepted; version 4 adds stable UUID share identifiers.
        Replace preserves exported UUIDs; append generates new ones for copies.
        Version-2 exports retain those empty paths with record IDs and timestamps.
        Unknown fields are rejected rather than discarded.
        """
        if mode not in ("append", "replace"):
            raise ValueError("mode must be 'append' or 'replace'")
        if not isinstance(payload, dict) or not isinstance(payload.get("postcards"), list):
            raise ValueError("payload must be an object with a 'postcards' list")
        unknown = set(payload) - {"format", "schema_version", "exported_at", "postcards"}
        if unknown:
            raise ValueError(f"unknown import fields: {', '.join(sorted(unknown))}")
        if "format" in payload and payload["format"] != "picture-postcard-manager":
            raise ValueError("unsupported import format")
        version = payload.get("schema_version", SCHEMA_VERSION)
        if type(version) is not int or version not in IMPORT_VERSIONS:
            raise ValueError(f"unsupported import schema_version: {version}")
        entries = payload["postcards"]
        if not all(isinstance(e, dict) for e in entries):
            raise ValueError("every postcard must be an object")
        with self._lock, self._conn:
            if mode == "replace":
                self._conn.execute("DELETE FROM postcards")
            for index, entry in enumerate(entries, start=1):
                # Migrated records retain their empty path on export and reimport.
                legacy = version == 1 or (
                    entry.get("front_image_path") == ""
                    and all(key in entry for key in ("id", "created_at", "updated_at"))
                )
                if legacy and entry.get("front_image_path") == "":
                    entry = {key: value for key, value in entry.items()
                             if key != "front_image_path"}
                try:
                    if payload.get("schema_version") == 4 and "uuid" not in entry:
                        raise ValueError("schema version 4 postcards must include uuid")
                    self._insert(entry, keep_id=(mode == "replace"), allow_legacy=legacy)
                except (ValueError, sqlite3.IntegrityError) as exc:
                    raise ValueError(f"postcard {index}: {exc}") from exc
        return len(entries)
