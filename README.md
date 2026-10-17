# Picture Postcard Manager

A minimal web application for managing a picture postcard collection.
It runs locally on a single machine or on a server for central access.

## Features

- Entry form to create, edit and delete postcards
- Browse mode with search
- Image selection with local previews for the front and back image
- SQLite database for persistence
- Export of the whole database to JSON and import from JSON (append or replace)
- English and German interface with a persistent language selector

## Architecture

Deliberately minimal — **no required third-party dependencies**. The only
exception is [Pillow](https://pypi.org/project/Pillow/), an **optional
dependency used solely for overview thumbnails** (see
[Optional dependencies](#optional-dependencies)); everything else, and the app
itself, runs on the standard library alone:

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
  thumbs.py        Optional thumbnail cache for overview previews (uses Pillow when installed)
  cleanup.py       CLI to list or delete orphaned uploaded images and their thumbnails
  static/          Web UI (index.html, app.js, languages.js, style.css)
    js/            Focused ES modules loaded by app.js (no build step):
                   dom, api, i18n, feedback, preview, tags, upload, routing,
                   sorting, filters, detail, overview, form, import, bulk
tests/             unittest-based API, database and localization tests
data/              Default local (non-Docker) database and images/ location (git-ignored)
Dockerfile         Container image for server deployment (installs optional deps by default)
compose.yaml       Docker Compose setup
compose.proxy.yaml Optional overlay: Caddy reverse proxy with TLS and basic auth
proxy/Caddyfile    Caddy configuration for the proxy overlay
requirements-optional.txt  Optional dependencies (Pillow, only for thumbnails)
```

The frontend is split into small native ES modules under `app/static/js/`;
`app.js` is the entry point loaded with `<script type="module">`. The browser
resolves the imports directly — there is no bundler, build step or third-party
dependency. The import graph is acyclic: shared primitives (`dom`, `api`,
`i18n`, `feedback`) are leaf modules, and `routing.js` never imports a view —
`app.js` injects the route handlers via `initRouting({...})`
(`tests/cycles_check.js` enforces this). The JavaScript runtime tests
concatenate the modules in dependency order (`tests/bundle.js`) so they keep
running without a module loader.

## User guide

Collectors and operators should use
[docs/user-guide.md](docs/user-guide.md). Every published GitHub Release
attaches a PDF of that guide, built from the exact release-tag commit and
named `picture-postcard-manager-user-guide-<tag>.pdf` (see
[Release user-guide PDF](#release-user-guide-pdf)). The PDF is not stored in
Git, and the guide source does not hard-code a release version: the pipeline
injects `{{VERSION}}` and `{{GENERATED_ON}}` at build time.

Build the PDF locally with one command (requires Docker; the renderer is the
digest-pinned `pandoc/latex:3.8.3` container image, so the build is identical
to CI):

```sh
python3 tools/pdf/build_pdf.py --version v0.2.0
```

This renders `docs/user-guide.md` to
`dist/picture-postcard-manager-user-guide-v0.2.0.pdf` (git-ignored) without
modifying the source. The generation date defaults to the committer date of
`HEAD`, so rebuilding the same commit produces the same PDF; override it with
`--date YYYY-MM-DD`. Validate the result:

```sh
pip install --require-hashes -r tools/pdf/requirements-validate.txt
python3 tools/pdf/validate_pdf.py \
  --pdf dist/picture-postcard-manager-user-guide-v0.2.0.pdf --version v0.2.0
```

Research that is not part of the user guide lives under `docs/research/`.
[Image-description services](docs/research/image-description-services.md) is a
dated survey for a possible later feature. It is not a collector task and is
not a PDF source.

## Running locally

```sh
python3 -m app
```

Then open <http://127.0.0.1:8000>.

## Optional dependencies

The application needs **no third-party packages**: `python3 -m app` runs on the
Python standard library alone. There is exactly one optional dependency:

- **Pillow — optional dependency, only for thumbnails.** The standard library
  cannot decode or resize JPEG, WebP or GIF, so the server-side
  [overview thumbnails](#overview-images) need an imaging library. When Pillow
  is not installed, thumbnail generation is simply disabled and thumbnail URLs
  transparently serve the original images — no errors, no behavior change
  beyond larger downloads.

Install it only if you want thumbnails outside Docker (use a virtualenv, not
the system Python):

```sh
pip install -r requirements-optional.txt
```

The Docker image installs the optional dependencies **by default**, because a
server deployment typically serves several clients over a network, where the
bandwidth savings matter most. Build with
`docker build --build-arg INSTALL_OPTIONAL=false .` for a
standard-library-only image. CI runs the test suite in both modes — with and
without Pillow.

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

The form stores four canonical fields:

| Field | Requirement | Description |
|-------|-------------|-------------|
| `front_image_path` | Required | Non-empty path or reference to the front image |
| `back_image_path` | Optional | Path or reference to the back image |
| `year` | Optional | Exactly four ASCII digits (for example `1908`); legacy free-text values remain readable and restorable from full exports |
| `description` | Optional | Free-form description |

Image paths are internal state: the form fills them by uploading the selected
images (see [Image selection and uploads](#image-selection-and-uploads)) and
never displays or edits them as text. Paths from imports or the API are stored
as provided. Optional values can be left empty.

The legacy `title` and `notes` fields were removed in schema version 5
([#23](https://github.com/schmidt-software/picture-postcard-manager/issues/23)).
Their content is not lost: the migration merges non-empty values verbatim into
`description` in the order title, notes, existing description, with exactly one
blank line between the text of adjacent pieces (newlines a value already ends
or starts with count towards that blank line, so nothing is duplicated and the
original text is never trimmed or altered). Empty or whitespace-only values are
skipped,
so records without legacy content keep their description unchanged.
The API rejects `title` and `notes` as unknown fields on create and update.

The dedicated `place` and `region` fields were removed in schema version 6
([#46](https://github.com/schmidt-software/picture-postcard-manager/issues/46));
location information lives in [tags](#tags) instead. The migration converts
every non-blank place and region value into a tag using exactly the tag
editor's rules: surrounding whitespace is trimmed, the trimmed text (including
any Unicode) is preserved verbatim, empty or whitespace-only values are
skipped, and exact duplicates are dropped. Existing tags keep their order; the
place is appended before the region, so a postcard whose place and region are
equal gains only one tag, and a value that already exists as a tag is not
added again. De-duplication is **case-sensitive**, matching the tag editor: a
place `wien` next to an existing tag `Wien` becomes a separate `wien` tag
rather than being merged. Migrated values remain discoverable through the
text search and the tag filter. The API rejects `place` and `region` as
unknown fields on create and update, and the obsolete `place`/`region` sort
and filter query parameters return the regular HTTP 400 validation error, so
outdated clients fail loudly instead of silently losing data.

**Downgrading after the schema-6 migration is not supported**: older versions
reject the newer database. Back up `/data` (database and images, see
[Complete backup and restore](#complete-backup-and-restore)) before upgrading
so you can return to the previous version with its matching data if needed.

When opening a database from an earlier schema, startup adds the canonical fields (schema 1),
the `tags` column (schema 2) and the `uuid` column (schema 4) as needed, merges the
legacy `title` and `notes` columns into `description` (schema 5), converts the
`place` and `region` columns into tags (schema 6) and drops the obsolete columns,
all in one transaction, and advances the SQLite `user_version`.
The obsolete columns are removed via a table rebuild (new table with the
current schema, rows copied, old table dropped, new one renamed), which works
on every SQLite version
(`ALTER TABLE ... DROP COLUMN` would require SQLite 3.35+).
Existing IDs, UUIDs, timestamps, the AUTOINCREMENT sequence (deleted IDs are
not reused), indexes on remaining columns and unrelated data are
preserved; indexes on the dropped columns are removed with them. The
migration is transactional and idempotent: a failed migration rolls back
completely and leaves the previous database intact, and reopening an already
migrated database changes nothing.
Migrated records without a front image remain available in browse and search;
they must be given a non-empty `front_image_path` before they can be edited.
The database migration does not discard legacy data.

## Image selection and uploads

The form shows one image picker per side instead of path fields. An empty
picker displays a localized placeholder; clicking, tapping or pressing
Enter/Space on the focused control opens the browser's file picker. A selected
file is previewed locally via an object URL (`URL.createObjectURL`) — nothing
is uploaded yet — and a trash button with a localized accessible label clears
the selection, its preview and the file input, so the same file can be chosen
again. Replaced and discarded previews have their object URLs revoked.

When the form is saved, pending selections are uploaded first and on success
only the corresponding hidden path state is set to the stored image's URL,
e.g. `/images/3f2a…9c.png`, which the postcard is then saved with. The front
image remains required and the back image optional. Because uploads happen
during save, abandoned forms leave no orphaned files; only a save that uploads
images but then fails to store the postcard can orphan the uploaded files (see
[cleanup](#cleaning-up-orphaned-images)).

When editing a postcard, stored same-origin images are shown as previews.
Replacing or removing an image only changes the association when the form is
saved; stored files are never deleted by the form.

- Supported formats: PNG, JPEG, GIF and WebP. The declared type must match the
  file's signature; SVG and other formats are rejected.
- Maximum size: 20 MiB (20,971,520 bytes) per image.
- Stored files get a random generated name; the client's filename and local path
  are never sent or used, and existing files are never overwritten.
- If an upload fails during save, the error is shown next to the picker, the
  selection and preview are kept, and the save is aborted so it can simply be
  retried; already uploaded files are reused instead of being uploaded again.
  Saving is disabled while uploads are running. Uploads whose form was
  switched, reset or cancelled in the meantime never affect the next form.
- Uploaded files are not deleted automatically when a postcard is deleted or its
  path changed; use the [orphaned-image cleanup](#cleaning-up-orphaned-images)
  command to remove unreferenced files.

Images are stored in `PPM_IMAGE_DIR`, which defaults to an `images` directory next
to the database file (`data/images` locally, `/data/images` in the Docker volume). Only files
with generated names that are regular files (not symlinks) directly inside this
directory and whose content matches their extension are served under `/images/`.

### Cleaning up orphaned images

Deleting a postcard or changing its image path can leave uploaded files behind
in `PPM_IMAGE_DIR`. The cleanup command lists or removes generated files that no
postcard references, including their cached thumbnails:

```sh
python3 -m app.cleanup                  # Dry run: list orphaned files only
python3 -m app.cleanup --delete         # Delete the listed orphaned files
```

It uses `PPM_DB_PATH` and `PPM_IMAGE_DIR` (or `--db` and `--image-dir`) with the
same defaults as the server. In the Docker setup, run it inside the container:

```sh
docker compose exec app python -m app.cleanup           # Dry run
docker compose exec app python -m app.cleanup --delete
```

Safety rules:

- Only files with generated upload names (32 hex characters plus `.png`, `.jpg`,
  `.gif` or `.webp`) directly inside the image directory are considered.
- A file is kept when its name appears as the last segment of any postcard's
  front or back image path, however the path was entered — including URLs with
  a query or fragment (`/images/<name>.png?v=1`), percent-encoded names and
  full URLs (`http://host/images/<name>.png`). When a value is ambiguous, the
  file is kept.
- Cached [thumbnails](#thumbnails) in the `thumbs/` subdirectory follow their
  originals: a thumbnail is kept exactly while its referenced original exists,
  and is removed when its original is orphaned or has vanished.
- Manually added files, other filenames, subdirectories and symlinks are never
  touched. JSON export/import and backups are unaffected; exports reference
  images by path only.
- Run the command while the collection is not being edited, and prefer a dry run
  (the default) before `--delete`. Deleted files are only recoverable from a
  [backup](#complete-backup-and-restore).

## Tags

Each postcard has any number of optional, free-form tags (none by default).
In the entry form, type a tag and press Enter or "Add tag"; each tag appears as a
chip with a remove button. Because tags are added one at a time, they may contain
commas, spaces and any Unicode text. Browse shows the tags and the search box also
matches tag text.

While typing in the tag input, an autocomplete list suggests previously used
tags whose beginning matches the typed text (ignoring surrounding whitespace).
Matching is case-insensitive and Unicode-aware: both sides are normalized to
NFC first (so composed and decomposed spellings like `é` vs `e` + combining
accent match in both directions) and then lowercased for the active UI locale
(`toLocaleLowerCase`). This is a locale lowercase fold, not full Unicode case
folding — for example `ss` does not match `ß`, while the capital `ẞ` does.
Suggestions keep their stored
spelling, exclude tags already selected on the postcard, are unique and sorted
alphabetically for the active UI language with exact-case prefix matches first.
While the list is open, Tab accepts the first (or arrow-selected) suggestion
and keeps focus in the input; otherwise Tab moves focus as usual. Arrow keys
move through the list, Enter accepts the active suggestion (or adds the typed
text as a new tag when none is active), Escape closes the list, and clicking
or tapping a suggestion accepts it. The input implements the accessible
combobox/listbox pattern and announces suggestion counts and accepted tags in
the UI language through a polite live region. Suggestions come from the cached
filter-values response (`/api/postcards/filters`) — no request is sent per
keystroke — and refresh after saving, deleting, JSON import and bulk image
import. If loading them fails, the list stays hidden and free tag entry keeps
working; brand-new tags can always be typed and added.

API rules: `tags` is an array of strings. Leading and trailing whitespace is
trimmed; blank tags and non-string values are rejected with HTTP 400. Exact
duplicates after trimming are dropped (comparison is case-sensitive, so `Berlin`
and `berlin` are different tags). Order is preserved and there is no limit on the
number of tags. On `PUT`, omitting `tags` keeps the existing tags and `"tags": []`
clears them. Search uses SQLite's `LIKE` on each decoded tag (via `json_each`),
not on the stored JSON text.

Tags are stored in the `tags` column as a JSON array string (default `[]`).

## Overview images

The overview shows compact front/back image previews, year, tags, ID and the
last update time. Description remains editable and is included in
storage and JSON exports, but is not shown as an overview column.

### Thumbnails

Overview previews of uploaded images request `/images/thumbs/<name>` instead of
the original. When [Pillow](#optional-dependencies) is installed, the server
answers with a resized thumbnail (at most 400 px on the longest side),
generated lazily on the first request — so images uploaded before this feature
get thumbnails too — and cached in a `thumbs/` directory inside
`PPM_IMAGE_DIR`. Cache files are written atomically (temp file + rename), so
concurrent requests never see partial files. EXIF orientation is applied,
animated GIFs use their first frame, and transparent images stay PNG while
opaque ones become JPEG. Images with more than 64 million pixels are not
decoded (decompression-bomb protection), and corrupt images never fail the
request: in both cases, and whenever Pillow is missing, the thumbnail URL
serves the original image unchanged. Thumbnails are served with the same
hardening as originals (generated names only, regular non-symlinked files,
matching content type, `nosniff`, CSP sandbox). Detail pages always use the
originals. The cache is derived data: it can be regenerated at any time and
is maintained by the [cleanup command](#cleaning-up-orphaned-images).

The overview loads postcards in pages of 100 rows; **Show more postcards**
appends the next page. Searching or changing a filter resets to the first
page. With several thousand postcards the first page stays fast because only
one page is queried and rendered (measured locally with 5,000 postcards:
~10 ms for a 100-row page versus ~30 ms for the full unpaginated list, before
image loading).

### Filters

Controls above the overview narrow the collection by an exact
year and by any number of tags; the choices list the values that currently
exist in the collection. The tag filter uses **AND semantics**: a postcard
matches only when it carries every selected tag (it may carry additional
tags). Selected tags appear as removable chips with a **Clear tags** action;
the add-select offers the remaining tags in a deterministic locale-aware
order with their stored spelling, excluding already-selected ones. Tag
matching is exact and case-sensitive, like the tag editor.
Filters combine with each other, with the search box, with sorting and with
pagination
(**Show more postcards** continues the filtered, sorted list), and **Reset filters**
clears them all, including every selected tag. The selection is stored in the
browser's local storage and restored on reload, like the interface language;
a single-tag selection stored by an older version is migrated automatically.
The selected tags are also mirrored into the overview URL as repeated
`tag` parameters (for example `?tag=Vienna&tag=Night`). On entering the
overview the URL is authoritative: its tag parameters are applied over any
stored selection, and a URL without `tag` parameters means no tag filter —
so reload, Back/Forward navigation and shared overview URLs always show
exactly the selection they encode; URLs
with a single `tag` parameter keep working. The choices refresh
whenever the collection changes — after saving, deleting (also directly in
the overview), importing a JSON file, or a bulk image import — so they always
list only existing values. A
selected or restored value that no postcard offers anymore (for example
because its last postcard was just deleted) remains selected and simply
yields an empty result until it is removed or reset.

The REST API accepts the same filters as exact-match query parameters on
`GET /api/postcards` (`year`, `tag`), combinable with `q`,
`limit` and `offset`. The `tag` parameter may be repeated; a postcard must
contain every requested tag (exact, case-sensitive element match against the
JSON tag array, never a substring or raw-JSON text match). Duplicate repeated
values are deduplicated before the query runs and do not change the result;
blank `tag` values return HTTP 400. `GET /api/postcards/filters` returns the
distinct non-empty values for each filterable field. The former `place` and
`region` filter parameters were removed with their fields and now return
HTTP 400.

### Sorting

A **Sort by** selector above the overview orders the postcards by
year or last update, ascending or descending (toggled with a direction button);
**Newest first** (highest ID first) is the default. Sorting combines with the
search box and the filters, and the selection is stored in the browser's local storage and
restored on the next visit, like the interface language. Changing the sort key
or direction resets to the first page; **Show more postcards** continues in the
selected order, because the server sorts the complete (filtered) result before
cutting the requested page.

Text fields sort case-insensitively. Free-text `year` values sort by the first
number they contain (`ca. 1910` and `1910-1915` both sort as 1910, ties by
text), years without a number sort after numbered ones alphabetically, and
postcards without a value for the chosen field always come last.

The REST API accepts the same options as
`GET /api/postcards?sort=<key>&dir=<asc|desc>` with keys
`year` and `updated`, combined freely with `q`, the filter parameters, `limit`
and `offset`; invalid
values - including the removed `place` and `region` keys - return HTTP 400,
and omitting `sort` keeps the newest-first order.

Previews load lazily from browser-accessible URLs on the application's own
origin. Missing or unavailable images show a localized fallback instead of a
broken-image icon. External hosts, `file:` and active-content URLs are not loaded.
Filesystem paths that are not served by the app cannot be previewed; their
stored values are unchanged.

## Postcard detail pages and sharing

Click a row in the overview (or focus it and press Enter) to open its detail page.
Photos are displayed prominently alongside the stored year,
description and tags; empty optional fields are omitted. Images use the same
same-origin restrictions and unavailable-image fallbacks as the overview.
Choose **Edit** to change the postcard, or **Back to overview** to return.

Each overview row also provides edit and delete icon buttons with localized
tooltips and accessible labels. These actions do not open the detail page.
Editing opens `#postcards/<uuid>/edit`, which always loads the postcard's
current data from the API, so the edit form can be reloaded and Back/Forward
work as expected. Deletion requires confirmation; cancelling or a failed request
leaves the postcard in the overview.

Each postcard has a direct link such as
`http://127.0.0.1:8000/#postcards/b962a358-8899-4000-8999-6973bac5d599`.
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

### UUID share identifiers

Each postcard receives a random UUIDv4 from the server. Existing databases are
migrated transactionally, assigning UUIDs without changing metadata, tags, image
paths, numeric IDs or timestamps. UUIDs remain unchanged across edits and restarts
and cannot be assigned or modified through create/update requests.

Detail pages and share links accept only canonical lowercase UUIDv4 identifiers;
the former numeric-ID detail links are no longer supported. UUID lookup uses
`GET /api/postcards/by-uuid/<uuid>`. Numeric API IDs remain available for internal
management and editing.

UUIDs make share URLs difficult to guess, but are **not access control**. The
management API still supports listing postcards and numeric-ID operations.
Use the existing reverse-proxy authentication to restrict access to the collection.

Schema-version-4 exports include `uuid` in every record. A **replace** import
preserves UUIDs and therefore existing share links; an **append** import assigns
fresh UUIDs and numeric IDs to every copy. Explicit version-4 records must include
valid UUIDs, and duplicate UUIDs in a replace import are rejected transactionally.
Versions 1–3 remain importable and receive new UUIDs when none are present.

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
returned as HTTP errors and logged. The healthcheck calls the lightweight
`GET /api/health` endpoint using Python's standard library. Check startup or health failures with
`docker compose ps` and `docker compose logs --tail=100 app`.

A named volume is used instead of a host bind mount because SQLite databases
newly created on Docker Desktop (macOS) bind mounts can fail on the first write
with `attempt to write a readonly database` (`SQLITE_READONLY_DBMOVED`). The
`./data` directory is used only when running directly with `python3 -m app`.

The build context is allowlisted in `.dockerignore`: local data, images, Git
metadata, backups, environment files and Python caches are not sent to the
builder or included in the image.

### Running as a non-root user

The container runs the application as the unprivileged user `ppm` (UID 1000,
GID 1000 by default), not as root. The image creates `/data` owned by that
user, so a **fresh named volume works without extra steps**: Docker initializes
the volume from the image, and the database, uploaded images and thumbnails
are all writable. Verify the effective user and write access of a running
stack with:

```sh
docker compose exec app id          # uid=1000(ppm) gid=1000(ppm) — never uid=0
docker compose exec app sh -c 'touch /data/.write-test && rm /data/.write-test && echo /data is writable'
```

The UID/GID are build arguments. For a **Linux host bind mount** owned by
another account, match the container user to the directory owner instead of
changing the directory:

```sh
PPM_UID="$(id -u)" PPM_GID="$(id -g)" docker compose up -d --build
```

(put the values in `.env` to make them stick). On Docker Desktop for macOS and
Windows, bind-mount file sharing already maps ownership, so the defaults work
there; named volumes are unaffected by host accounts on every platform.

#### Upgrading an existing root-owned `/data` (migration)

Deployments created **before** the non-root change have a `/data` volume or
bind mount owned by root, which the `ppm` user cannot write. The symptom after
upgrading is a startup failure (directory or SQLite errors in
`docker compose logs app`) or `attempt to write a readonly database`. Make a
[complete backup](#complete-backup-and-restore) first, then fix the ownership
once with a one-off root container and restart:

```sh
docker compose stop &&
  docker compose run --rm --no-deps --user 0 app \
    chown -R 1000:1000 /data &&
  docker compose up -d --build
```

Use your custom `PPM_UID:PPM_GID` values instead of `1000:1000` if you
override them. The command changes only ownership of `/data` (database,
SQLite `-wal`/`-shm` sidecar files, `images/` and `images/thumbs/`); file
contents, names and modes are untouched, so all postcards and images are
preserved. The one-off container runs as root solely for this `chown` and is
removed afterwards; the application container itself always stays
unprivileged. For a Linux bind mount you can equally run
`sudo chown -R 1000:1000 ./your-data-dir` on the host.

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

When updating across the switch to the non-root container user, also apply the
[ownership migration](#upgrading-an-existing-root-owned-data-migration) once.

Restarts, container recreation and image rebuilds keep the volume and its data.

### Complete backup and restore

**JSON export is not a full backup:** it contains records and image paths, but
no image bytes. A full backup must copy the SQLite database **and** the complete
image directory together. The commands below archive the whole `/data` volume,
including any SQLite journal files. The cached thumbnails under
`images/thumbs/` are derived data: they are regenerated automatically from the
originals, so they are optional in backups and may be excluded to save space.
Stop the application during backup and
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

### Access control and network deployment

The default Compose setup is for local access only: the app is published on
`127.0.0.1` and is not reachable from other machines. The application has **no
built-in authentication**; for network access, use the bundled reverse-proxy
overlay (or an equivalent setup).

#### Threat model

- **UUID share links are not access control.** They are merely hard to guess;
  anyone who obtains a link (logs, browser history, forwarded message) can open
  the postcard, and `GET /api/postcards` lists the entire collection anyway.
- **The API and `/images/` expose everything.** Without a proxy in front, any
  client that can reach the port can read, modify and delete all data.
- The app itself speaks plain HTTP and does not evaluate `X-Forwarded-For` or
  `X-Forwarded-Proto`; TLS termination and authentication are the proxy's job.

#### Reverse-proxy overlay (Caddy)

`compose.proxy.yaml` adds a [Caddy](https://caddyserver.com/) container that
terminates TLS and requires HTTP basic auth for the whole site — the UI, every
API endpoint and `/images/`. With the overlay the app container is no longer
published at all; Caddy is the only entry point (ports 80/443). The plain
`docker compose up` behavior is completely unchanged.

1. Create your environment file and set a username and password hash
   (credentials live only in the git-ignored `.env`, never in the repository):

   ```sh
   cp .env.example .env
   docker run --rm caddy:2.10 caddy hash-password --plaintext 'your-password'
   ```

   Put the username in `PPM_PROXY_USER` and the bcrypt hash in
   `PPM_PROXY_PASSWORD_HASH`, wrapped in single quotes:

   ```sh
   PPM_PROXY_PASSWORD_HASH='$2a$14$abc…'
   ```

   Docker Compose does not interpolate inside single quotes in `.env`, so the
   `$` characters reach the container unchanged. An unquoted hash is mangled
   (Compose treats `$2a`, `$14`, … as variable references), so always quote it.

2. Start the stack with both files:

   ```sh
   docker compose -f compose.yaml -f compose.proxy.yaml up -d --build
   ```

3. Open `https://localhost` and log in with your credentials.

**TLS options** via `PPM_PROXY_HOST` in `.env`:

- `localhost` (default): Caddy issues a certificate from its internal CA.
  Browsers warn about it unless you trust that CA; fine for local or LAN use.
- A real public hostname (DNS pointing at the machine, ports 80/443 reachable):
  Caddy obtains and renews publicly trusted certificates automatically (ACME).

What the overlay protects: all HTTP access through the proxy requires
authentication and is encrypted. What it does **not** protect: anyone with
shell or Docker access on the host can still reach the app container and the
data volume directly, and basic auth offers a single shared credential with no
per-user accounts or audit trail. The container healthcheck is unaffected — it
runs inside the app container against `127.0.0.1` and bypasses the proxy by
design.

Stop the stack with the same file list
(`docker compose -f compose.yaml -f compose.proxy.yaml down`); backup and
restore commands from the previous section work unchanged.

## Container images (GHCR)

Every published GitHub Release automatically builds and pushes a
multi-architecture image (`linux/amd64` and `linux/arm64`) to the GitHub
Container Registry at `ghcr.io/schmidt-software/picture-postcard-manager`,
built from the exact release tag commit
(workflow: `.github/workflows/release-image.yml`). The image includes the
optional Pillow dependency, so overview thumbnails work out of the box, and it
runs as the unprivileged `ppm` user exactly like a local Compose build (see
[Running as a non-root user](#running-as-a-non-root-user)).

### Tag convention

| GitHub Release          | GHCR tags                      | `latest` updated |
|-------------------------|--------------------------------|------------------|
| Stable `vX.Y.Z`         | `X.Y.Z`, `vX.Y.Z`, `latest`    | yes              |
| Prerelease `vX.Y.Z-rc.1`| `X.Y.Z-rc.1`, `vX.Y.Z-rc.1`    | **never**        |
| Draft release           | nothing published              | no               |

So release `v0.1.0` publishes `0.1.0`, `v0.1.0` and `latest`. The plain and
`v`-prefixed version tags are aliases of the same image; use whichever matches
your tooling. `latest` always points at the most recent **stable** release;
prereleases never move it. Tags that are not semver (`vMAJOR.MINOR.PATCH` with
an optional prerelease suffix) are rejected by the workflow and publish
nothing. Ordinary branch pushes and pull requests never publish images.

### Pulling and running

```sh
docker pull ghcr.io/schmidt-software/picture-postcard-manager:0.1.0

docker run -d --name picture-postcard-manager \
  -p 127.0.0.1:8000:8000 \
  -v postcard-data:/data \
  ghcr.io/schmidt-software/picture-postcard-manager:0.1.0
```

Then open <http://127.0.0.1:8000>. The named volume `postcard-data` holds the
SQLite database (`/data/postcards.db`) and uploaded images (`/data/images/`),
and the `127.0.0.1:` prefix publishes the port on the loopback interface only,
matching the Compose defaults. The container runs as the non-root `ppm` user
(UID/GID 1000); a fresh named volume is initialized writable from the image.
For bind mounts or existing root-owned volumes, see the ownership notes and
migration steps under
[Running as a non-root user](#running-as-a-non-root-user). All the usual
environment variables (next section) can be overridden with `-e`.

If the GHCR package is private or pulls require authentication in your
environment, log in first with a token that has `read:packages`:
`docker login ghcr.io`. Whether anonymous pulls work depends on the package's
visibility settings on GitHub.

Docker Compose can use the published image instead of a local build by
replacing `build: .` with
`image: ghcr.io/schmidt-software/picture-postcard-manager:0.1.0` in
`compose.yaml`; everything else (volume, healthcheck, port mapping) stays the
same.

## Release announcements (Mastodon)

Every published **stable** GitHub Release is automatically announced on the
Mastodon instance <https://kanoa.de>
(workflow: `.github/workflows/announce-release.yml`). The status contains the
release name, tag, a truncated excerpt of the release notes and a link to the
release page. Drafts and pre-releases are never announced, matching the
container-image convention above where pre-releases are previews that never
become `latest`.

The workflow authenticates with the `MASTODON_ACCESS_TOKEN` repository
secret: a Mastodon access token for the announcing account on `kanoa.de`
with the `write:statuses` scope (create it under *Preferences → Development →
New application*). Without the secret the workflow fails without posting
anything; the token value itself is never logged.

## Release user-guide PDF

Every published GitHub Release (stable **and** prerelease) automatically
builds the user guide as a PDF and attaches it as a release asset named
`picture-postcard-manager-user-guide-<tag>.pdf`
(workflow: `.github/workflows/release-user-guide.yml`). The guide source is
taken from `docs/user-guide.md` **at the exact release-tag commit**, never
from the default branch, and the release tag is validated as strict semver
and verified to be an ancestor of `main`, exactly like the container-image
workflow above.

The renderer is the digest-pinned `pandoc/latex:3.8.3` container image
(pandoc 3.8.3 with TeX Live/XeLaTeX,
`pandoc/latex@sha256:dd0dd153f681ec264094c04011e34459e8de61fe95712020ab4dfbff1117b015`),
invoked by `tools/pdf/build_pdf.py`. The injected generation date is the
committer date of the tag commit and seeds `SOURCE_DATE_EPOCH`, so rebuilding
the same tag reproduces the same PDF. After the build,
`tools/pdf/validate_pdf.py` (hash-pinned `pypdf`) checks the PDF magic, page
count, title, injected version, selectable text, bookmarks, internal and
external links, absent placeholders, and embedded fonts; only then does a
separate, minimally privileged job upload the asset. A rerun replaces the
identically named asset (`gh release upload --clobber`) instead of
duplicating it, and a build or validation failure fails the workflow without
uploading anything.

A manual `workflow_dispatch` run of the same workflow backfills the PDF onto
an **existing** release tag with identical validation. Exactly one release
predates the guide: `v0.1.0`, where no `docs/user-guide.md` exists at the
tag. Only for that literal tag does the workflow build the retrospective
snapshot committed under `docs/releases/v0.1.0/user-guide.md`; any other tag
without a guide at its commit fails the build (there is no generic snapshot
fallback). That snapshot was audited against the application source at
`v0.1.0` (visible image-path fields, place/region fields, single-tag filter,
schema version 5, no version footer, the published
`ghcr.io/schmidt-software/picture-postcard-manager:0.1.0` image) and states
its retrospective provenance on the first page. The snapshot is frozen
documentation for that tag and is not updated with new features.

Pull requests that touch the application, documentation, deployment files,
or workflows build and validate both guides in CI
(workflow: `.github/workflows/docs-pdf.yml`), so a broken guide fails the PR
instead of the release. `tests/test_user_guide_pdf.py` checks the pipeline's
security and consistency properties without Docker.

## Configuration

| Variable      | Default              | Description              |
|---------------|----------------------|--------------------------|
| `PPM_HOST`    | `127.0.0.1`          | Interface to bind to     |
| `PPM_PORT`    | `8000`               | Port to listen on        |
| `PPM_DB_PATH` | `data/postcards.db`  | Path to the SQLite file  |
| `PPM_IMAGE_DIR` | `images` next to the database file | Directory for uploaded images (created at startup) |
| `PPM_VERSION` | `dev` | Public version string shown in the UI footer (see [Application version](#application-version)) |

The Dockerfile sets `PPM_HOST=0.0.0.0`, `PPM_PORT=8000`,
`PPM_DB_PATH=/data/postcards.db` and `PPM_IMAGE_DIR=/data/images`.
Compose uses the host's `PPM_PORT` only for port publishing; it does not
automatically forward host environment variables into the container.

## Application version

Every page shows the running application version in a shared footer, e.g.
`Version 0.1.0` (issue #44). The value has a **single authoritative runtime
source**: the server reads the `PPM_VERSION` environment variable and exposes
it via `GET /api/version`; the frontend fetches it once at startup and renders
it as plain text (safely escaped, localized label). The endpoint responds with
`Cache-Control: no-cache`, so the footer never shows a stale version after a
deploy. Only the public version string is exposed — no commit hashes or other
operational details.

How the version is supplied:

- **Local runs** (`python3 -m app`): unset by default, the footer shows the
  explicit `dev` fallback. Override with `PPM_VERSION=0.1.0 python3 -m app`.
- **Docker Compose** (local build): the `PPM_VERSION` build argument defaults
  to `dev`; override with `PPM_VERSION=0.1.0 docker compose up -d --build` or
  an `.env` entry, or set it as a runtime environment variable.
- **Release images** (GHCR): the release workflow derives the version from the
  release tag (`v0.1.0` → `0.1.0`) and bakes it into the image as the
  `PPM_VERSION` environment variable, so the published image displays its
  release version without any configuration or runtime file rewriting.

Blank, overlong (more than 100 characters) or non-printable values fall back
to `dev`.

## REST API

| Method | Path                         | Description                                   |
|--------|------------------------------|-----------------------------------------------|
| GET    | `/api/health`                | Lightweight health check (server and database) |
| GET    | `/api/version`               | Public version string of the running build (see [Application version](#application-version)) |
| GET    | `/api/postcards?q=<text>&year=&tag=&tag=&sort=<key>&dir=<asc\|desc>&limit=<n>&offset=<n>` | List postcards (search, exact-match filters — `tag` repeatable with AND semantics — optional sorting and pagination) |
| GET    | `/api/postcards/filters`     | Distinct values for the overview filters      |
| POST   | `/api/postcards`             | Create a postcard                             |
| GET    | `/api/postcards/<id>`        | Get a postcard                                |
| PUT    | `/api/postcards/<id>`        | Update a postcard                             |
| DELETE | `/api/postcards/<id>`        | Delete a postcard                             |
| GET    | `/api/export`                | Export all postcards as JSON                  |
| POST   | `/api/import?mode=append\|replace` | Import postcards from an export file    |
| POST   | `/api/images`                | Upload an image (raw bytes, see below)        |
| GET    | `/images/<name>`             | Get an uploaded image                         |

### Listing and pagination

`GET /api/postcards` returns all postcards (newest first) when no pagination
parameters are given, which keeps existing clients and exports working. Optional
`limit` (positive integer) and `offset` (non-negative integer, default 0) select
a page; both combine with `q` and with the filter parameters. Invalid values
return HTTP 400. `GET /api/export` always exports the whole collection.

The server uses one SQLite connection per request thread with WAL journal mode
for file databases, so reads do not block while another request writes. Each
connection is closed when its request finishes, so the number of open
connections stays bounded regardless of how many requests have been served.
Uploads
and image downloads are streamed in 1 MiB chunks instead of being buffered
completely in memory; the 20 MiB per-image limit is unchanged, and an upload
that ends early is rejected without leaving a partial file.

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

The current export uses schema version 6. Each record includes the four canonical
fields, `tags` (array of strings), and the `id`, `uuid`, `created_at`
and `updated_at` values.

```json
{
  "format": "picture-postcard-manager",
  "schema_version": 6,
  "exported_at": "2026-01-01T12:00:00+00:00",
  "postcards": [
    {
      "id": 1,
      "uuid": "b962a358-8899-4000-8999-6973bac5d599",
      "front_image_path": "images/front.jpg",
      "back_image_path": "images/back.jpg",
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

Version-1 to version-5 imports remain supported; records without `tags` import
with an empty tag list, and legacy `title` and `notes` values are merged into
`description` using the same format as the database migration (title, then
notes, then description, preserved verbatim and separated by exactly one blank
line of combined whitespace at each join; empty
values are skipped). Legacy `place` and `region` values in version 1-5
imports are converted into tags using the same rules as the database
migration (trimmed, blank values skipped, appended after the record's own
tags with place before region, exact case-sensitive duplicates dropped).
Version-6 exports round-trip exactly and reject `title`,
`notes`, `place` and `region` as unknown fields; payloads without a
`schema_version` are treated as the current version and reject them too, so
obsolete fields are never silently discarded. An invalid `tags`
value fails the whole import (nothing is imported).

Version-1 imports remain supported. Such older records may have no front image
path; they retain their original values and can be repaired later by supplying
the required path. Exporting and reimporting preserves legacy records, including
their empty paths. Imports reject unknown fields, unsupported versions and invalid
records with actionable errors. Imports are transactional: if any record fails,
no records in that import are retained.

## Bulk image import

**Import / Export → Bulk image import** creates postcards from several images at
once when digitizing a collection:

- Select any number of image files. Files named `<base>-front.<ext>` and
  `<base>-back.<ext>` (also `_front`/`_back`, case-insensitive) with the same
  base name become one postcard with front and back images. Every other file
  becomes a postcard with only a front image.
- Each file uses the normal upload validation (PNG/JPEG/GIF/WebP, matching
  signature, 20 MiB limit) and receives a generated name.
- A failed file does not abort the others. The result list reports every
  created postcard and every failure with its reason; a back image that fails
  still produces a postcard from its front image. A `-back` file without a
  matching `-front` file is reported and skipped, because the front image is
  required.
- Year, description and tags can be added afterwards by editing
  each created postcard.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

Localization tests use only Python's standard library. When Node.js is available,
they also run JavaScript runtime regression checks; those tests are skipped if
Node.js is not installed. The thumbnail generation tests need the optional
Pillow dependency and skip themselves when it is not installed; the fallback
behavior without Pillow is always tested. CI runs the suite both without and
with Pillow.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

This project is licensed under the [MIT License](LICENSE)
(SPDX identifier: `MIT`). Published container images include the
`org.opencontainers.image.licenses=MIT` label and ship the `LICENSE`
file at `/srv/app/LICENSE`.
