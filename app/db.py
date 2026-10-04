"""SQLite persistence layer for postcards."""

import sqlite3
import threading
from datetime import datetime, timezone

SCHEMA_VERSION = 1

# Fields that can be set by clients. Extend this list (and the schema) when
# new input fields are introduced.
EDITABLE_FIELDS = ("title", "notes")

SCHEMA = """
CREATE TABLE IF NOT EXISTS postcards (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL DEFAULT '',
    notes       TEXT NOT NULL DEFAULT '',
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
        with self._lock, self._conn:
            self._conn.executescript(SCHEMA)
            self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def close(self):
        self._conn.close()

    @staticmethod
    def _clean(data):
        return {k: str(data[k]) for k in EDITABLE_FIELDS if k in data and data[k] is not None}

    def list(self, query=None):
        sql = "SELECT * FROM postcards"
        params = ()
        if query:
            sql += " WHERE title LIKE ? OR notes LIKE ?"
            params = (f"%{query}%",) * 2
        sql += " ORDER BY id DESC"
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params)]

    def get(self, postcard_id):
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM postcards WHERE id = ?", (postcard_id,)
            ).fetchone()
        return dict(row) if row else None

    def _insert(self, data, keep_id=False):
        fields = self._clean(data)
        fields["created_at"] = data.get("created_at") or _now()
        fields["updated_at"] = data.get("updated_at") or fields["created_at"]
        if keep_id and data.get("id") is not None:
            fields["id"] = int(data["id"])
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        cur = self._conn.execute(
            f"INSERT INTO postcards ({cols}) VALUES ({marks})", tuple(fields.values())
        )
        return cur.lastrowid

    def create(self, data):
        with self._lock, self._conn:
            new_id = self._insert(data)
        return self.get(new_id)

    def update(self, postcard_id, data):
        fields = self._clean(data)
        fields["updated_at"] = _now()
        assignments = ", ".join(f"{k} = ?" for k in fields)
        with self._lock, self._conn:
            cur = self._conn.execute(
                f"UPDATE postcards SET {assignments} WHERE id = ?",
                (*fields.values(), postcard_id),
            )
        return self.get(postcard_id) if cur.rowcount else None

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
        """
        if mode not in ("append", "replace"):
            raise ValueError("mode must be 'append' or 'replace'")
        if not isinstance(payload, dict) or not isinstance(payload.get("postcards"), list):
            raise ValueError("payload must be an object with a 'postcards' list")
        entries = payload["postcards"]
        if not all(isinstance(e, dict) for e in entries):
            raise ValueError("every postcard must be an object")
        with self._lock, self._conn:
            if mode == "replace":
                self._conn.execute("DELETE FROM postcards")
            for entry in entries:
                self._insert(entry, keep_id=(mode == "replace"))
        return len(entries)
