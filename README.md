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
data/              Default local (non-Docker) database and images/ location (git-ignored)
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
to the database file (`data/images` locally, `/data/images` in the Docker volume). Only files
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

## Overview images

The overview shows compact front/back image previews, place, year, tags, ID and the
last update time. Region and description remain editable and are included in
storage and JSON exports, but are not shown as overview columns.

Previews load lazily from browser-accessible URLs on the application's own
origin. Missing or unavailable images show a localized fallback instead of a
broken-image icon. External hosts, `file:` and active-content URLs are not loaded.
Filesystem paths that are not served by the app cannot be previewed; their
stored values are unchanged.

## Postcard detail pages and sharing

Click a row in the overview (or focus it and press Enter) to open its detail page.
Photos are displayed prominently alongside the stored place, region, year,
description and tags; empty optional fields are omitted. Images use the same
same-origin restrictions and unavailable-image fallbacks as the overview.
Choose **Edit** to change the postcard, or **Back to overview** to return.

Each postcard has a direct link such as `http://127.0.0.1:8000/#postcards/42`.
Opening or reloading it fetches that postcard from the API. Browser Back/Forward
and manually changing the URL fragment work without server-side page routing.
**Copy link** copies the URL to the clipboard; if clipboard access is unavailable
or denied, the visible read-only URL is selected for manual copying.

Sharing does not make the application publicly reachable or bypass access
controls. Recipients need network access to the installation and any credentials
required by its reverse proxy. A localhost link is only useful on the computer
running the app; for other recipients use the installation's reachable hostname.
Missing/deleted postcards and invalid links display a clear message instead of
an edit form or stale information.

## Running locally with Docker Compose

Install Docker with the Compose plugin, start the Docker daemon, then run these
commands from the checkout directory:

```sh
docker compose up -d --build
docker compose ps
```

Open <http://127.0.0.1:8000>. Compose publishes **only on the host's loopback
interface**, not to the local network. If port 8000 is occupied, use
`PPM_PORT=18008 docker compose up -d --build` and open <http://127.0.0.1:18008>.
To keep the chosen host port across subsequent commands, put `PPM_PORT=18008` in
a local `.env` file or export it in your shell. Inside the container the app
always listens on `0.0.0.0:8000`; Compose's `PPM_PORT` selects the host port only.

Data is stored in the Compose-managed named volume `postcard-data`, mounted at
`/data` in the container (Docker name `picture-postcard-manager_postcard-data`;
see `docker volume ls`). The container stores the SQLite database at
`/data/postcards.db` and uploaded images in `/data/images/`. The volume lives in
Docker's storage outside the container filesystem and outside this checkout.
It is independent of the checkout directory name because `compose.yaml` sets the
project name. Startup creates the database parent and image directories,
including with empty storage. Directory or SQLite initialization failures stop
startup with an error in `docker compose logs app`; image upload failures are
returned as HTTP errors and logged. The healthcheck reads the postcard API using
Python's standard library. Check startup or health failures with
`docker compose ps` and `docker compose logs --tail=100 app`.

A named volume is used instead of a host bind mount because SQLite databases
newly created on Docker Desktop (macOS) bind mounts can fail on the first write
with `attempt to write a readonly database` (`SQLITE_READONLY_DBMOVED`). The
`./data` directory is used only when running directly with `python3 -m app`.

The build context is allowlisted in `.dockerignore`: local data, images, Git
metadata, backups, environment files and Python caches are not sent to the
builder or included in the image.

### Shutdown, restart, rebuild and update

```sh
docker compose stop                           # Stop; retain the container and data
docker compose start                          # Start the stopped container
docker compose restart                        # Restart without changing the image
docker compose down                           # Remove containers/network, retain the volume
docker compose up -d --build                  # Rebuild and start again
docker compose up -d --build --force-recreate # Explicitly replace the container
```

**Never run `docker compose down -v` or `docker volume rm`** for this project
unless you intend to delete all postcards and images; both remove the volume.

To update, make a complete backup below first (including before any database
migration), then update the checkout and rebuild:

```sh
git pull --ff-only
docker compose up -d --build
docker compose ps
```

Restarts, container recreation and image rebuilds keep the volume and its data.

### Complete backup and restore

**JSON export is not a full backup:** it contains records and image paths, but
no image bytes. A full backup must copy the SQLite database **and** the complete
image directory together. The commands below archive the whole `/data` volume,
including any SQLite journal files. Stop the application during backup and
restore so the copy is consistent. The one-off `docker compose run` containers
use the application image (which includes `tar`), do not publish ports and are
removed afterwards.

Backup from the checkout directory (each run creates a new archive name):

```sh
mkdir -p backups
backup="ppm-$(date +%Y%m%d-%H%M%S).tar.gz"
docker compose stop &&
  docker compose run --rm --no-deps -v "$PWD/backups:/backup" app \
    tar -czf "/backup/$backup" -C /data . &&
  docker compose start
tar -tzf "backups/$backup"   # Should list ./postcards.db and ./images/
```

If the backup fails, the app stays stopped; fix the error before restarting.
Copy the archive to a safe location outside this checkout. Store backups
securely: they contain your collection and images.

To restore a trusted backup, first save the current volume, then replace its
contents completely. Extracting over existing data would mix stale images or
database journal files with the snapshot.

```sh
backup="ppm-YYYYMMDD-HHMMSS.tar.gz"    # Archive in ./backups
tar -tzf "backups/$backup"              # Inspect before restoring
docker compose down &&
  docker compose run --rm --no-deps -v "$PWD/backups:/backup" app \
    tar -czf "/backup/before-restore-$(date +%Y%m%d-%H%M%S).tar.gz" -C /data . &&
  docker compose run --rm --no-deps -v "$PWD/backups:/backup:ro" app \
    sh -c 'tar -tzf "/backup/$1" >/dev/null &&
      find /data -mindepth 1 -delete &&
      tar -xzf "/backup/$1" -C /data' sh "$backup" &&
  docker compose up -d --build
```

Keep the `before-restore-*` archive until you have checked the restored records
and front/back images in the browser. Use an application version compatible
with the backed-up schema (older versions may reject a newer database). To
restore on another machine or a fresh checkout, copy the archive into its
`backups/` directory and use the same commands.

### Migrating from the earlier `./data` bind mount

Earlier versions of `compose.yaml` stored Docker data in the checkout's `./data`
directory. To move it into the named volume once (the copy refuses to overwrite
a non-empty volume and leaves `./data` unchanged):

```sh
docker compose down &&
  docker compose run --rm --no-deps -v "$PWD/data:/legacy:ro" app \
    sh -c 'if [ -n "$(ls -A /data)" ]; then
        echo "volume is not empty; not migrating" >&2; exit 1
      fi && cp -a /legacy/. /data/' &&
  docker compose up -d --build
```

If the volume already contains data, nothing is copied and the app stays
stopped; start it again with `docker compose up -d`. Verify your postcards and
images, then keep `./data` as a backup or remove it yourself. Direct Python deployments with custom storage paths must back up the
database file and image directory together in the same stopped state.

### Network deployment

This Compose setup is for local access; it does not expose a public service.
The application has no built-in authentication. Any separately configured
network deployment must provide TLS and access control through a reverse proxy
(e.g. Caddy, nginx).

## Configuration

| Variable      | Default              | Description              |
|---------------|----------------------|--------------------------|
| `PPM_HOST`    | `127.0.0.1`          | Interface to bind to     |
| `PPM_PORT`    | `8000`               | Port to listen on        |
| `PPM_DB_PATH` | `data/postcards.db`  | Path to the SQLite file  |
| `PPM_IMAGE_DIR` | `images` next to the database file | Directory for uploaded images (created at startup) |

The Dockerfile sets `PPM_HOST=0.0.0.0`, `PPM_PORT=8000`,
`PPM_DB_PATH=/data/postcards.db` and `PPM_IMAGE_DIR=/data/images`.
Compose uses the host's `PPM_PORT` only for port publishing; it does not
automatically forward host environment variables into the container.

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
