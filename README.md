# Picture Postcard Manager

A minimal web application for managing a picture postcard collection.
It runs locally on a single machine or on a server for central access.

## Features

- Entry form to create, edit and delete postcards
- Browse mode with search
- Image upload for the front and back image paths
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
  images.py        Validation and storage of uploaded images
  static/          Web UI (index.html, app.js, languages.js, style.css)
tests/             unittest-based API, database and localization tests
data/              Default location of the SQLite database and images/ (git-ignored)
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

Image paths can be typed manually or filled by uploading an image (see
[Image uploads](#image-uploads)); manually entered paths are stored as entered.
Optional values can be left empty. Existing
`title` and `notes` values remain in the database and in exports for compatibility,
but are not part of the current entry form.

When opening a database from an earlier schema, startup adds the six fields (schema 1)
and the `tags` column (schema 2) as needed, in one transaction, with
empty-string defaults in a transaction and advances the SQLite `user_version`.
Existing IDs, timestamps, titles, notes, indexes and unrelated data are preserved.
Migrated records without a front image remain available in browse and search;
they must be given a non-empty `front_image_path` before they can be edited.
The database migration does not discard legacy data.

## Image uploads

Next to each image path field, **Choose front image** and **Choose back image**
open the browser's file picker. The selected file is uploaded to the server, and on
success only the corresponding path field is set to the stored image's URL, e.g.
`/images/3f2a…9c.png`. The front image remains required and the back image optional.
Manual paths can still be entered at any time; typing into a field while its upload
is running discards that upload's result.

- Supported formats: PNG, JPEG, GIF and WebP. The declared type must match the
  file's signature; SVG and other formats are rejected.
- Maximum size: 20 MiB (20,971,520 bytes) per image.
- Stored files get a random generated name; the client's filename and local path
  are never sent or used, and existing files are never overwritten.
- If an upload fails, the error is shown next to the button and the previous path
  is kept. Saving is disabled while an upload is running. Results of uploads that
  finish after the form was switched, reset or cancelled are ignored.
- Uploaded files are not deleted when a postcard is deleted or its path changed.

Images are stored in `PPM_IMAGE_DIR`, which defaults to an `images` directory next
to the database file (`data/images` locally, `/data/images` in Docker). Only files
with generated names that are regular files (not symlinks) directly inside this
directory and whose content matches their extension are served under `/images/`.

## Tags

Each postcard has any number of optional, free-form tags (none by default).
In the entry form, type a tag and press Enter or "Add tag"; each tag appears as a
chip with a remove button. Because tags are added one at a time, they may contain
commas, spaces and any Unicode text. Browse shows the tags and the search box also
matches tag text.

API rules: `tags` is an array of strings. Leading and trailing whitespace is
trimmed; blank tags and non-string values are rejected with HTTP 400. Exact
duplicates after trimming are dropped (comparison is case-sensitive, so `Berlin`
and `berlin` are different tags). Order is preserved and there is no limit on the
number of tags. On `PUT`, omitting `tags` keeps the existing tags and `"tags": []`
clears them. Search uses SQLite's `LIKE` on each decoded tag (via `json_each`),
not on the stored JSON text.

Tags are stored in the `tags` column as a JSON array string (default `[]`).

## Running on a server

```sh
docker compose up -d --build
```

The database is stored in `./data/postcards.db` and uploaded images in
`./data/images/` on the host; both persist in the mounted `/data` volume.
The application has no built-in authentication; when exposing it to a network,
put it behind a reverse proxy (e.g. Caddy, nginx) that provides TLS and access control.

## Configuration

| Variable      | Default              | Description              |
|---------------|----------------------|--------------------------|
| `PPM_HOST`    | `127.0.0.1`          | Interface to bind to     |
| `PPM_PORT`    | `8000`               | Port to listen on        |
| `PPM_DB_PATH` | `data/postcards.db`  | Path to the SQLite file  |
| `PPM_IMAGE_DIR` | `images` next to the database file | Directory for uploaded images (created on first upload) |

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
| POST   | `/api/images`                | Upload an image (raw bytes, see below)        |
| GET    | `/images/<name>`             | Get an uploaded image                         |

### Image upload

Send the raw image bytes as the request body with a `Content-Length` header and a
`Content-Type` of `image/png`, `image/jpeg`, `image/gif` or `image/webp`
(multipart form data is not used):

```sh
curl --data-binary @front.jpg -H "Content-Type: image/jpeg" http://127.0.0.1:8000/api/images
```

A successful upload returns `201 Created`:

```json
{"path": "/images/3f2a0c5e8b9d4e7fa1b2c3d4e5f60718.jpg", "content_type": "image/jpeg", "size": 48213}
```

Store `path` in `front_image_path` or `back_image_path`. Errors return JSON
`{"error": "..."}` with status `400` (empty or malformed request), `411` (missing
`Content-Length`), `413` (larger than 20 MiB), `415` (unsupported type or content
that does not match it) or `500` (the server could not store the file; details are
logged on the server only).

### JSON export format

The current export uses schema version 3. Each record includes the six canonical
fields, `tags` (array of strings), plus `title` and `notes` for compatibility, and the `id`, `created_at`
and `updated_at` values.

```json
{
  "format": "picture-postcard-manager",
  "schema_version": 3,
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
      "tags": ["Berlin, Mitte", "street view"],
      "created_at": "2026-01-01T12:00:00+00:00",
      "updated_at": "2026-01-01T12:00:00+00:00"
    }
  ]
}
```

Exports contain image paths only, not image files. Back up or move the image
directory (`PPM_IMAGE_DIR`, by default `data/images`) together with the JSON export
or database; uploaded `/images/...` paths only work on an installation that has
the same image files.

Version-1 and version-2 imports remain supported; records without `tags` import
with an empty tag list. Version-3 exports round-trip tags exactly. An invalid `tags`
value fails the whole import (nothing is imported).

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
