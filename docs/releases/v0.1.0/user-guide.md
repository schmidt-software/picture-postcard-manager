---
title: Picture Postcard Manager User Guide
subtitle: For collectors and operators
document_type: user-guide
language: en
audience: end-users
# The PDF pipeline replaces these two placeholders from the validated release
# tag and the deterministic generation date. Do not hard-code a release
# version in this file.
version: "{{VERSION}}"
generated_on: "{{GENERATED_ON}}"
source: docs/releases/v0.1.0/user-guide.md
pdf_asset: "picture-postcard-manager-user-guide-{{VERSION}}.pdf"
---

# Picture Postcard Manager User Guide

This guide explains how to install Picture Postcard Manager, keep its data
safe, and record a postcard collection. It is written for collectors and for
the person who runs the application. It is not a contributor guide.

## About this edition

| Item | Value |
| --- | --- |
| Application version | {{VERSION}} |
| Generated on | {{GENERATED_ON}} |
| Guide source | `docs/releases/v0.1.0/user-guide.md` |

> **Note:** **Provenance.** This edition was written after the release it
> describes. The release tag itself predates the user guide, so no guide
> source exists at that tag. This snapshot was authored retrospectively from
> a review of the application source code at the release tag, is stored in
> the repository keyed to that tag, and documents only behavior that release
> actually has. Later releases build their guide from the release commit
> itself.

> **Note:** Commands are meant to be copied. Run Docker commands from the
> directory that contains `compose.yaml`. Replace angle-bracket placeholders
> such as `<version>` before running a command. Do not paste a real
> password into a file that is committed to Git.

## What the application is for

Picture Postcard Manager is a small web application for one postcard
collection. You use a browser to add postcards, attach front and back images,
search and filter the collection, and open a direct link to one postcard.

The application stores records in a single SQLite database and stores uploaded
images as files next to that database. It can run on one computer for local
use, or on a server when several people need to reach the same collection.

The interface is available in English and German. Postcard text, tags, file
names, and exported JSON are never translated.

What it does not do:

- It has no built-in user accounts.
- A shared postcard link is not a password.
- A JSON export contains image paths, not the image files.
- Deleting a postcard does not delete its uploaded image files.
- It does not show the running application version in the interface.

## Before you start

### Choose a deployment

| Mode | Who it is for | Address on first start |
| --- | --- | --- |
| Docker Compose from a local build | The usual single-computer or server install | `http://127.0.0.1:8000` |
| Python on the host | A single computer where Docker is not used | `http://127.0.0.1:8000` |

The Compose install listens on the host's loopback interface only. Other
computers cannot open that address. For access from other computers, add the
optional Caddy proxy in [Restrict network access](#restrict-network-access).

For Docker Compose you need Docker with the Compose plugin, a running Docker
daemon, enough disk for the database, images, and backups, and port 8000 free
on loopback or another host port you choose. For a direct Python run you need
Python 3.11 or newer; no third-party package is required. Install the
optional Pillow package only if you want smaller overview previews. See
[Overview thumbnails and Pillow](#overview-thumbnails-and-pillow).

## Install with Docker Compose

1. Install Docker and start its daemon.
2. In the application directory (the directory that contains `compose.yaml`),
   build and start the application:

   ```sh
   docker compose up -d --build
   docker compose ps
   ```

3. Open `http://127.0.0.1:8000`.

Compose publishes the application on `127.0.0.1` only. If port 8000 is already
in use, choose another host port:

```sh
PPM_PORT=18008 docker compose up -d --build
```

Then open `http://127.0.0.1:18008`. Inside the container the application
always listens on port 8000; `PPM_PORT` changes only the host port.

`docker compose ps` should show the `app` service as healthy after the start
period. The health check calls `http://127.0.0.1:8000/api/health` from inside
the container.

The container runs as the unprivileged user `ppm` (user id 1000, group id
1000), not as root, and stores the collection in the named Docker volume
`postcard-data`, mounted at `/data`.

### Direct Python start

From the application directory:

```sh
python3 -m app
```

Open `http://127.0.0.1:8000`. The process listens on `127.0.0.1` and port
8000 unless you set `PPM_HOST` and `PPM_PORT`. Stop it with Ctrl+C in that
terminal. Data remains in `data/` next to the application.

## First start and stored data

On first start the application creates an empty database and an empty image
directory. The Browse page shows **No postcards yet.**

| Install | Database | Images | Thumbnail cache |
| --- | --- | --- | --- |
| Docker Compose | `/data/postcards.db` | `/data/images/` | `/data/images/thumbs/` |
| Direct Python run | `data/postcards.db` | `data/images/` | `data/images/thumbs/` |

Docker stores the named volume outside the container. Stopping, restarting,
or rebuilding the container does not remove it.

> **Warning:** `docker compose down -v` and `docker volume rm` delete the
> volume. That deletes every postcard and uploaded image. Do not use either
> command unless that is the intended outcome.

## Everyday collection tasks

The header has three views: **Browse**, **New postcard**, and
**Import / Export**. **Language** is the language selector. English is the
default even when the browser is set to another language. Choose **Deutsch**
to switch to German, or **English** to switch back. The choice is remembered
in this browser only.

### Create a postcard

1. Choose **New postcard**.
2. Choose **Choose front image** and select a PNG, JPEG, GIF, or WebP file up
   to 20 MiB. The file is uploaded immediately; the page says **Uploading
   image…** and then **Image uploaded.** The stored path appears in the
   **Front image path** field.
3. Optionally choose **Choose back image** the same way. The back image is
   optional.
4. Optionally add the place, region, year, description, and tags.
5. Choose **Save**. The page confirms **Postcard saved.** and returns to
   Browse.

| Field | Required | What to enter |
| --- | --- | --- |
| **Front image path** | Yes | Filled by **Choose front image**, or typed |
| **Back image path** | No | Filled by **Choose back image**, or typed |
| **Place** | No | The town or place shown on the card |
| **Region** | No | The region, state, or country |
| **Year** | No | Free text, such as `1905`, `ca. 1910`, or `1910-1915` |
| **Description** | No | Any notes about the postcard |
| **Tags** | No | Any labels; see [Tags and search](#tags-and-search) |

The path fields are visible and editable text. An upload stores the file
under a generated name and writes that path into the field; the file name on
your computer is not stored. Typing into a path field during an upload
abandons that upload and keeps what you typed.

If the front image path is empty, the page says **Please enter the front
image path.** If an upload fails, the page says **Image upload failed:
{detail} The previous path was kept.** While an upload runs, **Save** is
unavailable and another attempt says **Please wait until the image upload has
finished.**

A file that is empty, larger than 20 MiB (20,971,520 bytes), or not PNG,
JPEG, GIF, or WebP is rejected and does not change the path field.

**Cancel** leaves the form without saving.

### Edit a postcard

Open the postcard, then choose **Edit**. You can also choose the edit icon in
the Browse row. Its accessible name is **Edit postcard #** followed by the
numeric ID. The form title becomes **Edit postcard #** and that ID.

The form loads the postcard's current record. Change the fields and choose
**Save**. The share link does not change, because the application keeps the
same share identifier. Replacing a path does not delete the old uploaded
file; see [Remove unreferenced images](#remove-unreferenced-images).

### View a postcard

In Browse, click a row, or focus the row and press Enter or Space. The detail
page title is **Postcard #** followed by the numeric ID. It shows the front
image and, when present, the back image, plus any stored place, region, year,
description, and tags. Empty optional fields are omitted.

Choose **Back to overview** to return. Browser Back and Forward also move
between the detail page, the edit form, and Browse.

A missing image shows **Image unavailable**. A side with no stored path shows
**No image**.

### Share a postcard

On the detail page, **Share postcard** shows **Link to this postcard**.
Choose **Copy link**. The page says **Link copied.** If the browser cannot
write to the clipboard, it says **The link could not be copied automatically.
Select and copy it manually.** and selects the address.

A share link contains a random lowercase UUID, for example:

`http://127.0.0.1:8000/#postcards/b962a358-8899-4000-8999-6973bac5d599`

Send people an address they can actually reach. A `127.0.0.1` link works only
on the computer running the application. For anyone else, use the server's
host name, and include the proxy login when the Caddy overlay is enabled.

The link is hard to guess. It is not access control. Anyone who can open the
application can still list the collection. An invalid link says **This
postcard link is invalid.** A deleted postcard says **This postcard does not
exist or has been deleted.**

### Filter, sort, and page through Browse

Browse columns are **ID**, **Front image**, **Back image**, **Place**,
**Year**, **Tags**, **Updated**, and **Actions**. Region and description are
stored and exported, but they are not columns.

The **Search…** box matches part of the stored text fields, including place,
region, year, description, image paths, and tag text.

The filter row has four lists: **Place**, **Region**, **Year**, and **Tag**.
Each starts at **All** and lists values that exist in the collection. Each
list selects one exact stored value; the **Tag** list matches postcards that
have that one tag. Filters and the search box apply at the same time.
**Reset filters** clears all four lists. It appears only when a filter is
active.

**Sort by** defaults to **Newest first**. You can sort by **Place**,
**Region**, **Year**, or **Updated**. After you pick one of those,
**Ascending** appears. Choose it to switch between **Ascending** and
**Descending**. Text sorting ignores letter case. A year is ordered by the
first number in the text, so `ca. 1910` and `1910-1915` both sort as 1910.
Years with no number sort after numbered years. Postcards with no value in
the chosen field sort last.

Search, filters, and sorting combine. The first page shows up to 100
postcards. **Show more postcards** appends the next page in the same order.
Changing the search, a filter, or the sort returns to the first page.

The browser remembers the language, sort, and filters for this site. A filter
value that no longer exists can remain selected and then match nothing. The
page shows **No postcards yet.** both for an empty collection and for a
search or filter with no rows. Clear the search or choose **Reset filters**
before assuming the collection is empty.

### Delete a postcard

> **Caution:** Deleting a postcard removes its database record. It does not
> remove the uploaded image files. The record itself can be recovered only
> from a backup or from a JSON export that still contains it.

1. Choose the delete icon in the Browse row, or open the postcard and choose
   **Delete** on the edit form.
2. The confirmation says **Delete this postcard?**
3. Choose **Delete** to confirm, or **Cancel** to keep the postcard.

The delete icon's accessible name is **Delete postcard #** followed by the
numeric ID. After deletion the page says **Postcard deleted.** If the request
fails, the postcard remains.

## Images

### Overview thumbnails and Pillow

Browse asks for a reduced preview of an uploaded image. The detail page
always uses the original.

When Pillow is installed, the first preview request creates a thumbnail at
most 400 pixels on the longest side and stores it in `images/thumbs/` inside
the image directory. Transparent images stay PNG. Other images are stored as
JPEG. Animated GIFs use the first frame. The application applies EXIF
orientation. Images it cannot decode are not thumbnailed; the preview request
then returns the original instead of failing.

Without Pillow, nothing is generated and the preview request returns the
original image. Browse still works. Downloads are larger.

The default Docker build installs Pillow. A direct Python run does not, until
you install it in a virtual environment:

```sh
pip install -r requirements-optional.txt
```

Thumbnail files are a cache. They are recreated from the originals and may be
omitted from a backup to save space.

### Add many images at once

Use **Import / Export**, then **Bulk image import**, when you are scanning a
box of cards.

The hint on that page says: **Select several images to create one postcard
per image. Files named …-front and …-back with the same base name become one
postcard.**

1. Choose **Choose images** and select the files.
2. The page reports how many files are selected.
3. Choose **Create postcards**.
4. Wait for **Creating postcards…** to finish.

The summary says how many postcards were created and how many files failed.
One bad file does not cancel the others. A back file with no matching front
file fails with **No matching front image was selected.** and creates nothing
for that file. The words `front` and `back` are matched without regard to
letter case; `-front`/`-back` and `_front`/`_back` both pair.

Bulk import does not read place, year, description, or tags from file names.
Add those afterward with **Edit**.

### Remove unreferenced images

Changing a path or deleting a postcard leaves the old uploaded file in place.
The cleanup command lists generated files that no postcard references, and
can delete those files after you review the list.

> **Caution:** `--delete` permanently removes the listed files from the image
> directory. It cannot restore them. Take a backup first, and run the listing
> command before the delete command. Do this while nobody is editing the
> collection.

Docker Compose:

```sh
docker compose exec app python -m app.cleanup
docker compose exec app python -m app.cleanup --delete
```

Direct Python run, from the application directory:

```sh
python3 -m app.cleanup
python3 -m app.cleanup --delete
```

The first command only prints orphaned files. The command only considers
regular files whose names were generated by an upload. It keeps a file when
any front or back path ends with that file name, and keeps a file when a path
is ambiguous. It also removes a cached thumbnail whose original is orphaned
or gone. It does not delete manually added files or symbolic links.

## Tags and search

Tags record a publisher, subject, or any other label. A postcard can have any
number of tags, including none. Use the separate **Place** and **Region**
fields for locations.

1. Open the postcard form.
2. Type in **New tag**.
3. Press Enter or choose **Add tag**.
4. To remove a tag, choose the **×** on its chip. The accessible name is
   **Remove tag** followed by the tag text.

A tag may contain spaces, commas, and other Unicode text because tags are
added one at a time. Leading and trailing spaces are removed. An exact
duplicate is ignored. Comparison is case-sensitive: `Wien` and `wien` are two
tags. Order is preserved.

The Browse **Tag** filter matches one whole tag exactly. The search box
matches tag text as part of a broader text search.

## Export and import JSON

JSON export is a portable copy of the records. It is not a complete backup,
because it does not contain image bytes. For a restorable copy of the
collection, use [Back up the collection](#back-up-the-collection).

### Download the records

1. Choose **Import / Export**.
2. Under **Export**, choose **Download database as JSON**.

The file name is `postcards-export.json`. The current file uses schema
version 5. Each postcard includes its numeric ID, share UUID, front and back
paths, place, region, year, description, tags, and created/updated
timestamps.

Keep the image directory with the JSON file if you move the collection. Paths
that begin with `/images/` work only on an installation that has those same
files.

### Import records

1. Choose **Import / Export**.
2. Choose **Choose JSON file**.
3. Choose one import mode:
   - **Append to existing postcards** adds copies. Each copy receives a new
     numeric ID and a new share link.
   - **Replace all existing postcards** deletes every current record, then
     imports the file. Original numeric IDs and share UUIDs in the file are
     kept, so existing share links still open the same records.
4. Choose **Import**.

> **Caution:** **Replace all existing postcards** asks **Replace ALL existing
> postcards?** This removes every current record even when the file is empty.
> It does not delete image files. Back up `/data`, or the direct-run `data/`
> directory, before replacing.

A successful import says how many postcards were imported. If any record in
the file is invalid, the whole import is cancelled and the previous records
remain.

Compatibility rules:

| File | What this application version does |
| --- | --- |
| Schema version 5 export | Imports as exported. Unknown fields are rejected. |
| Schema versions 1 through 4 | Still accepted. Missing tags become an empty list. |
| Older `title` and `notes` values | Non-empty values are merged into the description, in that order, separated by one blank line. |
| A version newer than 5 | Rejected. |

## Run the application day to day

### Stop, start, and update

From the Compose directory:

```sh
docker compose stop
docker compose start
docker compose restart
docker compose down
docker compose up -d --build
```

`stop` retains the container and the volume. `down` removes the container and
network but retains the volume. `down` does not use `-v` here on purpose.

To update a Compose checkout: back up `/data` first, update the checkout with
a fast-forward pull, then rebuild and check health:

```sh
git pull --ff-only
docker compose up -d --build
docker compose ps
```

> **Note:** This application version does not display its version in the
> interface and has no version endpoint. To know what is running, keep a note
> of the Git tag or commit you built, together with each backup.

### Upgrades and database migrations

The application migrates an older database automatically the first time the
new version opens it. If the migration fails, the previous database is left
unchanged and the application does not finish starting. The current database
schema is version 5; these are data-schema versions, not release numbers.

> **Warning:** After a newer schema has been written, an older application
> version will refuse the database. Downgrading is not supported. Keep the
> backup made before the upgrade, together with a note of the application
> version that created it.

### Permissions and the non-root container

The container runs as `ppm`, not as root. A new named volume is writable
without extra steps. A volume created by an older root container can be owned
by root; after an upgrade the log may show `attempt to write a readonly
database`. Back up first, then correct ownership once:

```sh
docker compose stop &&
  docker compose run --rm --no-deps --user 0 app \
    chown -R 1000:1000 /data &&
  docker compose up -d --build
```

Use your configured ids instead of `1000:1000` if you changed `PPM_UID` and
`PPM_GID`. On a Linux bind mount owned by another account, build with
matching ids instead:

```sh
PPM_UID="$(id -u)" PPM_GID="$(id -g)" docker compose up -d --build
```

## Back up and restore

> **Warning:** Stop the application before copying or restoring `/data`.
> Copying a live SQLite database can capture a partial write. JSON export
> does not include image bytes, so it cannot restore the pictures.

A complete backup is an archive of `/data`: `postcards.db`, any SQLite
sidecar files, and `images/`. The `images/thumbs/` cache is optional.

### Back up the collection

From the Compose directory:

```sh
mkdir -p backups
backup="ppm-$(date +%Y%m%d-%H%M%S).tar.gz"
docker compose stop &&
  docker compose run --rm --no-deps -v "$PWD/backups:/backup" app \
    tar -czf "/backup/$backup" -C /data . &&
  docker compose start
tar -tzf "backups/$backup"
```

The listing should include `./postcards.db` and `./images/`. Copy the archive
somewhere outside the application directory. Treat it as private: it contains
the collection and the images.

For a direct Python install, stop `python3 -m app`, then archive the database
file and the image directory with the same care.

### Restore a backup

> **Caution:** A restore replaces the current `/data` contents. The commands
> below first archive the current volume, then empty `/data`, then extract
> the selected backup.

Put the archive in `backups/` and set `backup` to its file name:

```sh
backup="ppm-YYYYMMDD-HHMMSS.tar.gz"
tar -tzf "backups/$backup"
docker compose down &&
  docker compose run --rm --no-deps -v "$PWD/backups:/backup" app \
    tar -czf "/backup/before-restore-$(date +%Y%m%d-%H%M%S).tar.gz" -C /data . &&
  docker compose run --rm --no-deps -v "$PWD/backups:/backup:ro" app \
    sh -c 'tar -tzf "/backup/$1" >/dev/null &&
      find /data -mindepth 1 -delete &&
      tar -xzf "/backup/$1" -C /data' sh "$backup" &&
  docker compose up -d --build
```

Keep the `before-restore-*` archive until you have checked records and both
image sides in the browser. Restore onto an application version compatible
with that database.

## Restrict network access

The default Compose setup binds to `127.0.0.1`. That is the access control
for a single computer: other machines cannot open the port.

The application has no login of its own. It serves the browser interface, the
API, and `/images/` over plain HTTP. A share UUID does not restrict listing,
editing, or deleting.

> **Warning:** Do not publish port 8000 on a public or shared network without
> a proxy that requires authentication. Anyone who can reach the port can
> read, change, and delete the collection.

### Add the Caddy proxy

`compose.proxy.yaml` adds Caddy 2.10 in front of the application. Caddy terminates
TLS and requires HTTP Basic Authentication for the whole site: the pages,
every API path, and `/images/`. With the overlay, the application port is no
longer published. Caddy is the only entry point, on ports 80 and 443.

1. Create a local environment file from the example:

   ```sh
   cp .env.example .env
   ```

2. Generate a password hash. Replace the sample password before running it:

   ```sh
   docker run --rm caddy:2.10 caddy hash-password --plaintext 'your-password'
   ```

3. Edit `.env`, which is ignored by Git: set `PPM_PROXY_USER` to the login
   name, `PPM_PROXY_PASSWORD_HASH` to the generated hash wrapped in single
   quotes, and `PPM_PROXY_HOST` to `localhost` or to the public host name
   browsers will use. An unquoted hash is corrupted because `$` is treated
   as a variable reference.

4. Start both files:

   ```sh
   docker compose -f compose.yaml -f compose.proxy.yaml up -d --build
   ```

5. Open `https://localhost` and sign in. Do not put that password in the
   repository.

With `PPM_PROXY_HOST=localhost`, Caddy uses its internal certificate
authority and browsers warn until that authority is trusted. With a public
host name that points at this machine and reachable ports 80 and 443, Caddy
requests and renews a publicly trusted certificate.

Basic Authentication encrypts the password only because TLS is in front of
it. The proxy does not provide personal accounts, permission levels, or an
audit log. Anyone with shell or Docker access on the host can still read the
volume and reach the application container directly.

## Privacy and security

- The collection stays on the computer or server where you installed the
  application. The application does not send postcards to a hosted account
  service.
- Browser storage on each visitor's computer remembers only the interface
  language, sort, and filters. It does not store postcard text or images.
- Uploaded files are renamed to random generated names. The original file
  name is not kept.
- Share links are unguessable addresses, not authorization.
- Without the proxy, network reachability is the only boundary. With the
  proxy, the shared password and TLS are the boundary, and host access
  bypasses both.
- Backups and JSON exports are copies of the collection. Store them where you
  would store the photographs themselves, not in a public directory or a Git
  checkout.
- `.env` holds the proxy login hash. Never commit it.

## Troubleshooting and recovery

Check health and the recent log before changing data:

```sh
docker compose ps
curl -fsS http://127.0.0.1:8000/api/health
docker compose logs --tail=100 app
```

A healthy response body is:

```json
{"status": "ok"}
```

| What you see | What it usually means | What to do |
| --- | --- | --- |
| Browser cannot open `127.0.0.1:8000` | The container is stopped, Docker is not running, or the host port is not 8000 | Run `docker compose ps`. Start Docker. Check `PPM_PORT`. |
| `app` is not healthy | Startup failed, often while creating or migrating `/data` | Read the log. Do not delete the volume. |
| `attempt to write a readonly database` | `/data` is owned by root | Follow [Permissions and the non-root container](#permissions-and-the-non-root-container) after a backup. |
| **Image unavailable** | The stored path does not resolve to an image | Edit the postcard and upload the image again, or restore `images/` from backup. |
| Upload says the image is too large or unsupported | The file is over 20 MiB, empty, or not a PNG, JPEG, GIF, or WebP | Choose a supported file. The previous path remains. |
| **No postcards yet.** after you know records exist | Search or filters exclude every row | Clear **Search…** and choose **Reset filters**. |

Recovery order when startup fails after an upgrade: leave the volume in
place, read the log, and if you need the previous known-good state, restore
the backup taken before the upgrade onto an application version compatible
with that backup. Do not run `docker compose down -v` as a repair step.

## Configuration reference

Set these only when the default is wrong.

| Variable | Default outside Docker | Docker value | Purpose |
| --- | --- | --- | --- |
| `PPM_HOST` | `127.0.0.1` | `0.0.0.0` inside the container | Interface the application binds to |
| `PPM_PORT` | `8000` | `8000` inside the container | Container listen port. In Compose, the host's `PPM_PORT` selects the published host port only. |
| `PPM_DB_PATH` | `data/postcards.db` | `/data/postcards.db` | SQLite file |
| `PPM_IMAGE_DIR` | `images` next to the database | `/data/images` | Uploaded images |
| `PPM_UID`, `PPM_GID` | Not used | `1000` and `1000` | User and group for a rebuilt image |
| `PPM_PROXY_HOST` | Used only with the proxy overlay | `localhost` | Name Caddy serves |
| `PPM_PROXY_USER` | Used only with the proxy overlay | None; required by the overlay | Basic Authentication user |
| `PPM_PROXY_PASSWORD_HASH` | Used only with the proxy overlay | None; required by the overlay | bcrypt hash, single-quoted in `.env` |

Useful operator endpoints, on the application origin:

| Method | Path | Result |
| --- | --- | --- |
| GET | `/api/health` | `{"status": "ok"}` when the server and database respond |
| GET | `/api/export` | Schema 5 JSON attachment named `postcards-export.json` |
| POST | `/api/import?mode=append` or `mode=replace` | Imports a JSON export |
| GET | `/images/<generated-name>` | One uploaded original |
| GET | `/images/thumbs/<generated-name>` | A thumbnail, or the original when no thumbnail can be made |

The project site is
<https://github.com/schmidt-software/picture-postcard-manager>.
