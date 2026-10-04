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
tests/             unittest-based API tests
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
such as `{id}` and `{count}`. Missing keys fall back to English. New UI text must
use a translation key, either through a `data-i18n` attribute (with separate
attributes for placeholders and accessible labels) or `translate()` in JavaScript.

Changing language updates labels, messages, confirmations and accessible form
validation without reloading the page. Postcard titles, notes, search text,
selected filenames and JSON data are never translated or modified.

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
| GET    | `/api/postcards?q=<text>`    | List postcards (optional full-text filter)    |
| POST   | `/api/postcards`             | Create a postcard                             |
| GET    | `/api/postcards/<id>`        | Get a postcard                                |
| PUT    | `/api/postcards/<id>`        | Update a postcard                             |
| DELETE | `/api/postcards/<id>`        | Delete a postcard                             |
| GET    | `/api/export`                | Export all postcards as JSON                  |
| POST   | `/api/import?mode=append\|replace` | Import postcards from an export file    |

### JSON export format

```json
{
  "format": "picture-postcard-manager",
  "schema_version": 1,
  "exported_at": "2026-01-01T12:00:00+00:00",
  "postcards": [
    { "id": 1, "title": "...", "notes": "...", "created_at": "...", "updated_at": "..." }
  ]
}
```

## Tests

```sh
python3 -m unittest discover -s tests -v
```

The localization tests use only Python's standard library. When Node.js is
available, they also run the JavaScript runtime regression tests; those tests
are skipped if Node.js is not installed.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
