"""SQLite persistence layer for postcards.

File databases use one connection per thread with WAL mode, so concurrent
requests do not serialize on a global lock. In-memory databases keep a single
shared connection guarded by a lock, because each new ``:memory:`` connection
would create a separate empty database.
"""

import json
import sqlite3
import threading
from datetime import datetime, timezone
from uuid import UUID, uuid4

SCHEMA_VERSION = 5
IMPORT_VERSIONS = (1, 2, 3, 4, 5)

POSTCARD_FIELDS = (
    "front_image_path", "back_image_path", "place", "region", "year", "description",
)
# Legacy columns removed in schema 5; their content is merged into description.
LEGACY_FIELDS = ("title", "notes")
TEXT_FIELDS = POSTCARD_FIELDS
EDITABLE_FIELDS = (*TEXT_FIELDS, "tags")
RECORD_FIELDS = (*EDITABLE_FIELDS, "id", "uuid", "created_at", "updated_at")

SCHEMA = """
CREATE TABLE IF NOT EXISTS postcards (
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
"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class _NoLock:
    """No-op context manager used when per-thread connections need no lock."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


_NO_LOCK = _NoLock()


def merge_legacy_fields(title, notes, description):
    """Merge the legacy title and notes values into the description.

    Values whose content is empty or only whitespace are skipped; all other
    values are preserved verbatim (never stripped or otherwise altered). The
    remaining pieces are joined in the order title, notes, description so
    that exactly one blank line separates the text of adjacent pieces:
    newlines a piece already ends or starts with count towards that blank
    line, so no duplicate blank lines are inserted at the joins. When title
    and notes are both empty, the description is returned unchanged.
    """
    pieces = [value for value in (title, notes) if value and value.strip()]
    if not pieces:
        return description
    if description and description.strip():
        pieces.append(description)
    merged = pieces[0]
    for piece in pieces[1:]:
        trailing = len(merged) - len(merged.rstrip("\n"))
        leading = len(piece) - len(piece.lstrip("\n"))
        merged += "\n" * max(0, 2 - trailing - leading) + piece
    return merged


class Database:
    def __init__(self, path):
        self._path = str(path)
        self._shared = self._path == ":memory:"
        self._lock = threading.Lock()
        self._local = threading.local()
        self._connections = []
        self._closed = False
        conn = self._open_connection()
        try:
            with self._lock, conn:
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                if version > SCHEMA_VERSION:
                    raise ValueError(f"unsupported database schema version: {version}")
                conn.execute("BEGIN")
                conn.execute(SCHEMA)
                columns = {
                    row["name"] for row in conn.execute("PRAGMA table_info(postcards)")
                }
                for field in POSTCARD_FIELDS:
                    if field not in columns:
                        conn.execute(
                            f"ALTER TABLE postcards ADD COLUMN {field} TEXT NOT NULL DEFAULT ''"
                        )
                if "tags" not in columns:
                    conn.execute(
                        "ALTER TABLE postcards ADD COLUMN tags TEXT NOT NULL DEFAULT '[]'"
                    )
                if "uuid" not in columns:
                    conn.execute("ALTER TABLE postcards ADD COLUMN uuid TEXT NOT NULL DEFAULT ''")
                    for row in conn.execute("SELECT id FROM postcards").fetchall():
                        conn.execute(
                            "UPDATE postcards SET uuid = ? WHERE id = ?",
                            (str(uuid4()), row["id"]),
                        )
                conn.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS postcards_uuid ON postcards(uuid)"
                )
                self._drop_legacy_columns(conn, columns)
                conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        except (sqlite3.Error, ValueError):
            self.close()
            raise
        if self._shared:
            self._shared_conn = conn

    def _open_connection(self):
        """Create and register a configured connection for the current thread."""
        conn = sqlite3.connect(self._path, check_same_thread=False, timeout=30)
        conn.row_factory = sqlite3.Row
        if not self._shared:
            # WAL lets readers run while a writer commits; NORMAL is durable
            # enough with WAL and avoids an fsync per transaction.
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
        with self._lock:
            self._connections.append(conn)
        self._local.conn = conn
        return conn

    @property
    def _conn(self):
        if self._closed:
            raise sqlite3.ProgrammingError("database is closed")
        if self._shared:
            return self._shared_conn
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._open_connection()
        return conn

    def close(self):
        """Close all connections; later operations raise sqlite3.ProgrammingError."""
        with self._lock:
            self._closed = True
            connections, self._connections = self._connections, []
        for conn in connections:
            conn.close()

    def release_thread_connection(self):
        """Close and unregister the calling thread's connection, if any.

        Request handlers call this when a request finishes so short-lived
        server threads do not leak connections; the next operation on this
        thread transparently opens a fresh one. The shared in-memory
        connection is never released this way, only by close().
        """
        if self._shared:
            return
        conn = getattr(self._local, "conn", None)
        if conn is None:
            return
        self._local.conn = None
        with self._lock:
            if conn in self._connections:
                self._connections.remove(conn)
        conn.close()

    def open_connection_count(self):
        """Return the number of currently registered connections (for tests)."""
        with self._lock:
            return len(self._connections)

    def _write_lock(self):
        """Serialize access for the shared in-memory connection only."""
        return self._lock if self._shared else _NO_LOCK

    def ping(self):
        """Raise sqlite3.Error when the database is not reachable."""
        # Resolve the connection first: for file databases _conn may register
        # a new per-thread connection, which itself takes the registry lock.
        conn = self._conn
        with self._write_lock():
            conn.execute("SELECT 1").fetchone()

    def _drop_legacy_columns(self, conn, columns):
        """Schema 5: merge legacy title/notes into description, then drop them.

        Runs on the explicit migration connection, inside the startup
        migration transaction, so a failure rolls everything back. Indexes
        that reference a dropped column are removed as well; SQLite cannot
        drop an indexed column otherwise.
        """
        legacy = [field for field in LEGACY_FIELDS if field in columns]
        if not legacy:
            return
        selected = ", ".join(("id", *legacy, "description"))
        for row in conn.execute(f"SELECT {selected} FROM postcards").fetchall():
            merged = merge_legacy_fields(
                row["title"] if "title" in legacy else "",
                row["notes"] if "notes" in legacy else "",
                row["description"],
            )
            if merged != row["description"]:
                conn.execute(
                    "UPDATE postcards SET description = ? WHERE id = ?",
                    (merged, row["id"]),
                )
        for index in conn.execute("PRAGMA index_list(postcards)").fetchall():
            name = index["name"]
            if name.startswith("sqlite_autoindex"):
                continue
            indexed = [
                info["name"]
                for info in conn.execute(f'PRAGMA index_info("{name}")')
            ]
            if any(field in indexed for field in legacy):
                conn.execute(f'DROP INDEX "{name}"')
        for field in legacy:
            conn.execute(f"ALTER TABLE postcards DROP COLUMN {field}")

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

    @staticmethod
    def _search_clause(query):
        # Tags are matched as decoded text, not as their JSON representation.
        clause = " WHERE " + " OR ".join(
            [f"{field} LIKE ?" for field in TEXT_FIELDS]
            + ["EXISTS (SELECT 1 FROM json_each(postcards.tags) WHERE value LIKE ?)"]
        )
        return clause, (f"%{query}%",) * (len(TEXT_FIELDS) + 1)

    def list(self, query=None, limit=None, offset=0):
        """Return postcards, newest first; limit/offset select an optional page."""
        if limit is not None and (type(limit) is not int or limit < 1):
            raise ValueError("limit must be a positive integer")
        if type(offset) is not int or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        sql = "SELECT * FROM postcards"
        params = ()
        if query:
            clause, params = self._search_clause(query)
            sql += clause
        sql += " ORDER BY id DESC"
        if limit is not None or offset:
            # SQLite requires LIMIT with OFFSET; -1 means unlimited.
            sql += " LIMIT ? OFFSET ?"
            params = (*params, -1 if limit is None else limit, offset)
        with self._write_lock():
            return [self._row(r) for r in self._conn.execute(sql, params)]

    def count(self, query=None):
        """Return the number of postcards matching the optional search query."""
        sql = "SELECT COUNT(*) FROM postcards"
        params = ()
        if query:
            clause, params = self._search_clause(query)
            sql += clause
        with self._write_lock():
            return self._conn.execute(sql, params).fetchone()[0]

    def get(self, postcard_id):
        with self._write_lock():
            row = self._conn.execute(
                "SELECT * FROM postcards WHERE id = ?", (postcard_id,)
            ).fetchone()
        return self._row(row) if row else None

    def get_by_uuid(self, value):
        self._validate_uuid(value)
        with self._write_lock():
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
        with self._write_lock(), self._conn:
            new_id = self._insert(data)
        return self.get(new_id)

    def update(self, postcard_id, data):
        if isinstance(data, dict) and "uuid" in data:
            raise ValueError("uuid is generated by the server and cannot be changed")
        fields = self._clean(data)
        with self._write_lock(), self._conn:
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
        with self._write_lock(), self._conn:
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
        Versions 1-4 are accepted; version 4 adds stable UUID share identifiers
        and version 5 removes the legacy title and notes fields. Imports of
        versions 1-4 merge non-empty title and notes values into description
        (see merge_legacy_fields); version-5 imports reject them as unknown.
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
        with self._write_lock(), self._conn:
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
                    if version < 5:
                        entry = self._merge_legacy_entry(entry)
                    if payload.get("schema_version", 0) >= 4 and "uuid" not in entry:
                        raise ValueError("schema version 4 and newer postcards must include uuid")
                    self._insert(entry, keep_id=(mode == "replace"), allow_legacy=legacy)
                except (ValueError, sqlite3.IntegrityError) as exc:
                    raise ValueError(f"postcard {index}: {exc}") from exc
        return len(entries)

    @staticmethod
    def _merge_legacy_entry(entry):
        """Map legacy title/notes of version 1-4 imports into description."""
        if "title" not in entry and "notes" not in entry:
            return entry
        entry = dict(entry)
        values = {}
        for field in (*LEGACY_FIELDS, "description"):
            value = entry.pop(field, None)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{field} must be a string or null")
            values[field] = value or ""
        entry["description"] = merge_legacy_fields(
            values["title"], values["notes"], values["description"]
        )
        return entry
