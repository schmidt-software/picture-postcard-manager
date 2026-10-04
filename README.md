# Picture Postcard Manager

A minimal web application for managing a picture postcard collection.
It runs locally on a single machine or on a server for central access.

## Features

- Entry form to create, edit and delete postcards
- Browse mode with search
- SQLite database for persistence
- Export of the whole database to JSON and import from JSON (append or replace)
- English and German interface with a persistent language selector

## Architecture

Deliberately minimal — **no third-party dependencies**:

| Layer    | Technology                                          |
|----------|-----------------------------------------------------|
| Backend  | Python 3.11+ standard library (`http.server`, `sqlite3`) |
| Database | SQLite (single file)                                |
| Frontend | Plain HTML, CSS and JavaScript (no build step)      |
| Hosting  | Directly via Python or as a Docker container        |

```
app/
  server.py        HTTP server, REST API, static file serving
  db.py            SQLite schema and data access
  static/          Web UI (index.html, app.js, languages.js, style.css)
tests/             unittest-based API, database and localization tests
data/              Default location of the SQLite database (git-ignored)
Dockerfile         Container image for server deployment
compose.yaml       Docker Compose setup
```

## Running locally

```sh
python3 -m app
```

Then open <http://127.0.0.1:8000>.

## Interface language

The interface defaults to English, regardless of the browser or operating system
language. Select **Deutsch** in the **Language** selector in the header to switch
to German (or **English** to switch back). The selection is stored in this browser's
local storage and restored on subsequent visits to the same site. If storage is
unavailable, the selection works for the current page only. An unknown stored
language falls back to English.

All interface translations are centralized in `app/static/languages.js`. To add
a language, register a resource object under its language code, copying the
English keys and translating their values. Set `languageName` to its native
name; the selector lists registered languages automatically. Preserve placeholders
such as `{id}`, `{count}`, `{fields}`, `{version}`, `{field}`, `{index}`, and
`{detail}`. Missing keys fall back to English. New UI text must use a translation
key, either through a `data-i18n` attribute (with separate attributes for
placeholders and accessible labels) or `translate()` in JavaScript.

Changing language updates labels, messages, confirmations and accessible form
validation without reloading the page. Postcard field values, search text,
selected filenames and JSON data are never translated or modified.

## Postcard fields and compatibility

The form stores six canonical fields:

| Field | Requirement | Description |
|-------|-------------|-------------|
| `front_image_path` | Required | Non-empty path or reference to the front image |
| `back_image_path` | Optional | Path or reference to the back image |
| `place` | Optional | Place shown on the postcard |
| `region` | Optional | Region associated with the place |
| `year` | Optional | Text, allowing approximate dates and ranges |
| `description` | Optional | Free-form description |

Image paths are stored as entered; the application does not upload, validate or
otherwise process image files. Optional values can be left empty. Existing
`title` and `notes` values remain in the database and in exports for compatibility,
but are not part of the current entry form.

When opening a database from the earlier schema, startup adds the six fields with
empty-string defaults in a transaction and advances the SQLite `user_version`.
Existing IDs, timestamps, titles, notes, indexes and unrelated data are preserved.
Migrated records without a front image remain available in browse and search;
they must be given a non-empty `front_image_path` before they can be edited.
The database migration does not discard legacy data.

## Running on a server

```sh
docker compose up -d --build
```

The database is stored in `./data/postcards.db` on the host.
The application has no built-in authentication; when exposing it to a network,
put it behind a reverse proxy (e.g. Caddy, nginx) that provides TLS and access control.

## Configuration

| Variable      | Default              | Description              |
|---------------|----------------------|--------------------------|
| `PPM_HOST`    | `127.0.0.1`          | Interface to bind to     |
| `PPM_PORT`    | `8000`               | Port to listen on        |
| `PPM_DB_PATH` | `data/postcards.db`  | Path to the SQLite file  |

## REST API

| Method | Path                         | Description                                   |
|--------|------------------------------|-----------------------------------------------|
| GET    | `/api/postcards?q=<text>`    | List postcards (searches stored fields)       |
| POST   | `/api/postcards`             | Create a postcard                             |
| GET    | `/api/postcards/<id>`        | Get a postcard                                |
| PUT    | `/api/postcards/<id>`        | Update a postcard                             |
| DELETE | `/api/postcards/<id>`        | Delete a postcard                             |
| GET    | `/api/export`                | Export all postcards as JSON                  |
| POST   | `/api/import?mode=append\|replace` | Import postcards from an export file    |

### JSON export format

The current export uses schema version 2. Each record includes the six canonical
fields plus `title` and `notes` for compatibility, and the `id`, `created_at`
and `updated_at` values.

```json
{
  "format": "picture-postcard-manager",
  "schema_version": 2,
  "exported_at": "2026-01-01T12:00:00+00:00",
  "postcards": [
    {
      "id": 1,
      "title": "",
      "notes": "",
      "front_image_path": "images/front.jpg",
      "back_image_path": "images/back.jpg",
      "place": "Example place",
      "region": "Example region",
      "year": "1905",
      "description": "Postcard description",
      "created_at": "2026-01-01T12:00:00+00:00",
      "updated_at": "2026-01-01T12:00:00+00:00"
    }
  ]
}
```

Version-1 imports remain supported. Such older records may have no front image
path; they retain their original values and can be repaired later by supplying
the required path. Exporting and reimporting preserves legacy records, including
their empty paths. Imports reject unknown fields, unsupported versions and invalid
records with actionable errors. Imports are transactional: if any record fails,
no records in that import are retained.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

Localization tests use only Python's standard library. When Node.js is available,
they also run JavaScript runtime regression checks; those tests are skipped if
Node.js is not installed.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
