---
title: Picture Postcard Manager User Guide
subtitle: For collectors and operators
document_type: user-guide
language: en
audience: end-users
# The PDF pipeline replaces these two placeholders from the validated release
# tag and the release commit's date. Do not hard-code a release version in this file.
version: "{{VERSION}}"
generated_on: "{{GENERATED_ON}}"
source: docs/user-guide.md
pdf_asset: "picture-postcard-manager-user-guide-{{VERSION}}.pdf"
---

<!-- pdf:title-page
title: Picture Postcard Manager User Guide
subtitle: For collectors and operators
version: {{VERSION}}
date: {{GENERATED_ON}}
source: docs/user-guide.md
-->

<!-- guide-topics: purpose, prerequisites, docker-compose, ghcr, first-start, persistence, backup, restore, upgrade, schema-migration, create, edit, view, share, filter, sort, delete, images, thumbnails, bulk-import, cleanup, tags, search, json-export, json-import, pillow, caddy, tls, basic-auth, threat-model, version-footer, troubleshooting, health, logs, permissions, recovery, privacy -->

# Picture Postcard Manager User Guide

This guide explains how to install Picture Postcard Manager, keep its data
safe, and record a postcard collection. It is written for collectors and for
the person who runs the application. It is not a contributor guide.

## About this edition

| Item | Value |
| --- | --- |
| Application version | {{VERSION}} |
| Generated on | {{GENERATED_ON}} |
| Guide source | `docs/user-guide.md` |

In the repository, `{{VERSION}}` and `{{GENERATED_ON}}` are placeholders. A
PDF attached to a GitHub Release replaces them with the validated release tag
and the date of the release commit. This file deliberately does not store a
release number, so the PDF and the running application cannot drift to two
different hard-coded versions.

The heading hierarchy is the table of contents. Callouts use the labels
**Note**, **Warning**, and **Caution** at the start of a blockquote. Those
labels are the accessible names of the callouts; the PDF pipeline should style
them, not replace them with color alone. See
[Appendix: PDF edition](#appendix-pdf-edition).

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

## Before you start

### Choose a deployment

| Mode | Who it is for | Address on first start | Where the collection is stored |
| --- | --- | --- | --- |
| Docker Compose from a local build | The usual single-computer or server install | <http://127.0.0.1:8000> | Named volume mounted at `/data` |
| Published container image | A server that should run a released build without a local source checkout | <http://127.0.0.1:8000> | Named volume mounted at `/data` |
| Python on the host | A single computer where Docker is not used | <http://127.0.0.1:8000> | `data/postcards.db` and `data/images/` next to the application |

The Compose and published-image installs listen on the host's loopback
interface only. Other computers cannot open that address. For access from
other computers, add the optional Caddy proxy in
[Restrict network access](#restrict-network-access).

### Prerequisites

For Docker Compose or the published image:

- Docker with the Compose plugin.
- A running Docker daemon.
- Enough disk for the database, original images, and backups.
- Port 8000 free on loopback, or another host port you choose.

For the Caddy proxy, also allow inbound ports 80 and 443 when browsers on
other computers must connect. Those proxy ports are published on the host's
network interfaces, not only on loopback.

For a direct Python run:

- Python 3.11 or newer.
- No third-party package is required.
- Install the optional Pillow package only if you want smaller overview
  previews. See [Overview thumbnails and Pillow](#overview-thumbnails-and-pillow).

> **Note:** The published container image and the default Docker build already
> include Pillow. A direct Python run does not, until you install it.

## Install with Docker Compose

1. Install Docker and start its daemon.
2. In the application directory (the directory that contains `compose.yaml`),
   build and start the application:

   ```sh
   docker compose up -d --build
   docker compose ps
   ```

3. Open <http://127.0.0.1:8000>.

Compose publishes the application on `127.0.0.1` only. If port 8000 is already
in use, choose another host port for this command and for later Compose
commands:

```sh
PPM_PORT=18008 docker compose up -d --build
```

Then open <http://127.0.0.1:18008>. To keep that choice, put `PPM_PORT=18008`
in a local `.env` file or export it in the shell. Inside the container the
application always listens on port 8000. `PPM_PORT` changes only the host port.

`docker compose ps` should show the `app` service as healthy after the start
period. The health check calls `http://127.0.0.1:8000/api/health` from inside
the container.

### Use the published image instead of a local build

Every published GitHub Release builds a container image from that release tag
for `linux/amd64` and `linux/arm64`. The image name is:

`ghcr.io/schmidt-software/picture-postcard-manager`

| GitHub Release | Image tags | `latest` updated |
| --- | --- | --- |
| Stable release tag | The version with and without a leading `v`, plus `latest` | Yes |
| Prerelease tag | The version with and without a leading `v` | No |
| Draft release | Nothing is published | No |

Replace `<version>` below with the release version **without** the leading
`v`. Do not invent a version; copy it from the release that matches the
database you intend to run.

```sh
docker pull ghcr.io/schmidt-software/picture-postcard-manager:<version>

docker run -d --name picture-postcard-manager \
  -p 127.0.0.1:8000:8000 \
  -v postcard-data:/data \
  ghcr.io/schmidt-software/picture-postcard-manager:<version>
```

Open <http://127.0.0.1:8000>.

The `127.0.0.1:` prefix keeps the port on loopback. The volume
`postcard-data` is the Docker volume created by that `docker run` command. A
Compose stack uses a different volume name,
`picture-postcard-manager_postcard-data`. They are not the same volume. To run
the published image in Compose, point the `app` service at
`ghcr.io/schmidt-software/picture-postcard-manager:<version>` instead of
`build: .`, and keep the existing volume.

If the registry asks you to log in, use `docker login ghcr.io` with an account
that can read packages. Whether anonymous pulls work depends on the package
visibility on GitHub.

The published image runs as the unprivileged user `ppm` (user id 1000, group
id 1000) and includes Pillow. Its footer shows the release version baked into
that image.

## First start and stored data

On first start the application creates an empty database and an empty image
directory. Refresh the browser. The Browse page shows **No postcards yet.**
The footer shows the running version. See
[Find the installed version](#find-the-installed-version).

| Install | Database | Images | Thumbnail cache |
| --- | --- | --- | --- |
| Docker Compose or `docker run` with `/data` | `/data/postcards.db` | `/data/images/` | `/data/images/thumbs/` |
| Direct Python run, default settings | `data/postcards.db` | `data/images/` | `data/images/thumbs/` |

Docker stores the named volume outside the container and outside the
application directory. Stopping, restarting, or rebuilding the container does
not remove it.

> **Warning:** `docker compose down -v` and `docker volume rm` delete the
> volume. That deletes every postcard and uploaded image. Do not use either
> command unless that is the intended outcome.

A direct Python run uses the `data/` directory next to the working directory.
That directory is separate from the Docker volume. Back up the database file
and the image directory together.

### Direct Python start

From the application directory:

```sh
python3 -m app
```

Open <http://127.0.0.1:8000>. The process listens on `127.0.0.1` and port
8000 unless you set `PPM_HOST` and `PPM_PORT`. Stop it with Ctrl+C in that
terminal. Data remains in `data/`.

## Everyday collection tasks

The header has three views: **Browse**, **New postcard**, and
**Import / Export**. **Language** is the language selector. English is the
default even when the browser is set to another language. Choose **Deutsch**
to switch to German, or **English** to switch back. The choice is remembered
in this browser only.

### Create a postcard

1. Choose **New postcard**.
2. Choose the **Front image** preview. An empty preview says **No image selected. Opens the file picker.** Click, tap, or press Enter or Space. The accessible name is **Choose front image**.
3. The selected file is shown at once. Nothing is uploaded until you choose **Save**.
4. Optionally choose the **Back image** preview the same way. The back image is optional.
5. Optionally add the four-digit year, description, and tags. Existing imported cards may still display older free-text years; correct or clear such a value before saving an edited card.
6. Choose **Save**.

The page says **Uploading image…** and then **Image uploaded.** while it stores the selected files. It then confirms **Postcard saved.** and returns to Browse.

| Field | Required | What to enter |
| --- | --- | --- |
| **Front image** | Yes | A PNG, JPEG, GIF, or WebP file, up to 20 MiB |
| **Back image** | No | The same kinds of file, or none |
| **Year** | No | Exactly four digits, such as `1905`; leave it empty when unknown |
| **Description** | No | Any notes about the postcard |
| **Tags** | No | Location and other labels; see [Tags and search](#tags-and-search) |

There is no visible path field. The application stores an uploaded file under a generated name. The file name on your computer is not stored.

To clear a selection before saving, choose the trash control. Its accessible name is **Remove front image** or **Remove back image**. The page says **Image removed.** Clearing a selection does not delete a file that was already stored. The association changes only if you then save, and the old file remains until cleanup.

If no front image is selected, the page says **Please choose a front image.** If another save is already uploading, the page says **Please wait until the image upload has finished.** **Save** is unavailable while that upload runs.

If an upload fails, the page says **Image upload failed: {detail} The selected image was kept.** The preview stays, so choose **Save** again. A side that already uploaded successfully is not uploaded a second time. **Cancel**, leaving the form, or opening another postcard discards an unfinished selection. That selection is not stored and is not attached to the next form.

A file that is empty, larger than 20 MiB, or not PNG, JPEG, GIF, or WebP does not replace a useful selection that is already shown.

**Cancel** leaves the form without saving.

### Edit a postcard

Open the postcard, then choose **Edit**. You can also choose the edit icon in
the Browse row. Its accessible name is **Edit postcard #** followed by the
numeric ID. The form title becomes **Edit postcard #** and that ID.

The form loads the postcard's current record. Change the fields and choose
**Save**. The share link does not change, because the application keeps the
same share identifier.

When you edit a postcard, a stored image on this application's site is shown in the preview. Replacing or removing it changes the postcard only after **Save**. The form does not delete the old file.

An older record that has no front image can still be found in Browse. It cannot be saved until you choose a front image.

### View a postcard

In Browse, click a row, or focus the row and press Enter or Space. The detail
page title is **Postcard #** followed by the numeric ID. It shows the front
image and, when present, the back image, plus any stored year, description,
and tags. Empty optional fields are omitted.

Choose **Back to overview** to return. Browser Back and Forward also move
between the detail page, the edit form, and Browse.

A missing image shows **Image unavailable**. A side with no stored path shows
**No image**.

### Share a postcard

On the detail page, **Share postcard** shows **Link to this postcard**. Choose
**Copy link**. The page says **Link copied.** If the browser cannot write to
the clipboard, it says **The link could not be copied automatically. Select
and copy it manually.** and selects the address.

A share link looks like this, with a real lowercase UUID in place of the
example identifier:

`http://127.0.0.1:8000/#postcards/b962a358-8899-4000-8999-6973bac5d599`

Send people the address they can actually reach. A `127.0.0.1` link works only
on the computer running the application. For anyone else, use the server's
host name, and include the proxy login when the Caddy overlay is enabled.

The link is hard to guess. It is not access control. Anyone who can open the
application can still list the collection. An invalid link says **This
postcard link is invalid.** A deleted postcard says **This postcard does not
exist or has been deleted.**

Numeric ID links are not share links. Editing still uses the numeric ID
internally; that does not make the ID a public address.

### Filter, sort, and page through Browse

Browse columns are **ID**, **Front image**, **Back image**, **Year**,
**Tags**, **Updated**, and **Actions**. Description is stored and exported,
but it is not a column.

The **Search…** box matches part of the year, description, stored image address, or tag text.

**Year** starts at **All** and lists years that exist in the collection. It matches one exact stored value.

**Tags** can select more than one tag. The list is labeled **Add tag filter**, and its first choice is **Add tag…**. Each selected tag appears as a chip under **Selected tag filters**. The page says **Tag filter {tag} added.**

A postcard is shown only when it has every selected tag. The match is exact and case-sensitive: `Wien` does not match `wien`. The year filter and the search box still apply at the same time.

To remove one tag, choose the **×** on its chip. The accessible name is **Remove tag filter {tag}**. The page says **Tag filter {tag} removed.** **Clear tags** removes every selected tag and says **All tag filters removed.** **Reset filters** clears the year and every tag filter. It appears only when a year or tag filter is active.

Selected tags stay visible even after the last postcard that used them is deleted. Remove them yourself; the application does not drop them silently. A selected tag that no postcard has simply shows no rows.

The browser address records the selected tags as repeated `tag` parameters, in the order you added them, for example `?tag=Wien&tag=Bridge`. Reloading the page, using Back and Forward, or sending that address keeps the same filters. An address with no `tag` parameter means no tag filter, even if this browser previously remembered one. An older address with one `tag` parameter still selects that one tag.

**Sort by** defaults to **Newest first**. You can sort by **Year** or
**Updated**. After you pick one of those, **Ascending** appears. Choose it to
switch between **Ascending** and **Descending**. Text sorting ignores letter
case. A year is ordered by the first number in the text, so `ca. 1910` and
`1910-1915` both sort as 1910. Years with no number sort after numbered years.
Postcards with no value in the chosen field sort last.

Search, filters, and sorting combine. The first page shows up to 100
postcards. **Show more postcards** appends the next page in the same order.
Changing the search, a filter, or the sort returns to the first page.

The browser remembers the language, sort, and filters for this site. It does not remember postcard text there. On Browse, the address is the source for the tag selection. If storage is blocked, the choices still work until you reload the page.

A filter value that no longer exists can remain selected and then match
nothing. The page shows **No postcards yet.** both for an empty collection and
for a search or filter with no rows. Clear the search or choose **Reset
filters** before assuming the collection is empty.

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

Orphaned uploaded files can be removed later. See
[Remove unreferenced images](#remove-unreferenced-images).

## Images

### Choose a front or back image

The form shows a clickable preview for **Front image** and **Back image**. There is no visible path field.

1. Click, tap, or focus the preview and press Enter or Space.
2. The accessible names are **Choose front image** and **Choose back image**.
3. An empty preview says **No image selected. Opens the file picker.**
4. A selected file is previewed immediately and the page says **Image selected.** The file stays on your computer until you choose **Save**.
5. The trash control clears that side. Its accessible name is **Remove front image** or **Remove back image**. The page says **Image removed.** You can choose the same file again.

Accepted files are PNG, JPEG, GIF, and WebP, up to 20 MiB (20,971,520 bytes) each. The file contents must match the declared type. SVG and other formats are rejected. A rejected file does not replace a useful selection that is already shown.

On **Save**, each newly selected file is uploaded. The page says **Uploading image…**, then **Image uploaded.** The stored name is generated. The original file name and the path on your computer are not stored. The front image is required. The back image is optional.

If the upload fails, the page says **Image upload failed: {detail} The selected image was kept.** Choose **Save** again. A side that already uploaded successfully is reused. **Save** is unavailable while an upload is running. Another save attempt says **Please wait until the image upload has finished.**

**Cancel**, leaving the form, or opening another postcard abandons an unfinished selection. It is not uploaded, and it is not attached to the next form.

Imported records and the API can still store an image address as text. Browse and the detail page display that image only when it is an `http` or `https` address on this application's own site. A disk path, a `file:` address, or a link to another website is stored but shown as **Image unavailable**. The form cannot type or edit those addresses.

When editing, a stored image on this site is shown in the preview. Replacing or clearing it changes the postcard only after **Save**. The old file is not deleted by the form.

### Overview thumbnails and Pillow

Browse asks for a reduced preview of an uploaded image. The detail page always
uses the original.

When Pillow is installed, the first preview request creates a thumbnail at most
400 pixels on the longest side and stores it in `images/thumbs/` inside the
image directory. Transparent images stay PNG. Other images are stored as JPEG.
Animated GIFs use the first frame. The application applies EXIF orientation.
Images larger than 64 million pixels, and images it cannot decode, are not
thumbnailed; the preview request then returns the original instead of failing.

Without Pillow, nothing is generated and the preview request returns the
original image. Browse still works. Downloads are larger.

| Install | Pillow |
| --- | --- |
| Published image | Included |
| Default `docker compose up -d --build` | Included |
| Image built with `INSTALL_OPTIONAL=false` | Not included |
| `python3 -m app` | Not included unless you install it |

To enable thumbnails for a direct Python run, use a virtual environment and
install the optional requirements file:

```sh
pip install -r requirements-optional.txt
```

Thumbnail files are a cache. They are recreated from the originals and may be
omitted from a backup to save space.

### Add many images at once

Use **Import / Export**, then **Bulk image import**, when you are scanning a
box of cards.

The hint on that page says: **Select several images to create one postcard per image. Files named …-front and …-back with the same base name become one postcard.**

1. Choose **Choose images** and select the files.
2. The page reports how many files are selected.
3. Choose **Create postcards**.
4. Wait for **Creating postcards…** to finish.

The summary says how many postcards were created and how many files failed.
One bad file does not cancel the others. A failed back image still creates a
postcard from its front image. A back file with no matching front file fails
with **No matching front image was selected.** and creates nothing for that
file.

Pairing is based on the file name before the extension:

| Selected files | Result |
| --- | --- |
| `bridge-front.jpg` and `bridge-back.jpg` | One postcard with both sides |
| `bridge_front.png` and `bridge_back.png` | One postcard with both sides; `_front` and `_back` also pair |
| `bridge.jpg` | One postcard with only a front image |
| `bridge-back.jpg` alone | Skipped; the front image is required |

The words `front` and `back` are matched without regard to letter case. If the
same base name has two front files, the extra file becomes its own postcard.

Bulk import does not read year, description, or tags from file names. Add
those afterward with **Edit**.

### Remove unreferenced images

Changing a path or deleting a postcard leaves the old uploaded file in place.
The cleanup command lists generated files that no postcard references, and can
delete those files after you review the list.

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

The first command only prints orphaned files. It prints **No orphaned images
found.** when there is nothing to remove. The Docker commands use the
container's `/data` paths. The Python commands use `PPM_DB_PATH` and
`PPM_IMAGE_DIR`, or `data/postcards.db` and the `images` directory next to it.

The command only considers regular files whose names were generated by an
upload (32 hexadecimal characters plus `.png`, `.jpg`, `.gif`, or `.webp`).
It keeps a file when any front or back path ends with that file name, including
paths with a query string or a full URL. When a path is ambiguous, it keeps
the file. It also removes a cached thumbnail whose original is orphaned or
gone. It does not delete manually added files, other names, or symbolic links.

## Tags and search

Tags are the place to record a town, region, publisher, subject, or any other
label. A postcard can have any number of tags, including none.

1. Open the postcard form.
2. Type in **New tag**.
3. Press Enter or choose **Add tag**.
4. To remove a tag, choose the **×** on its chip. The accessible name is
   **Remove tag** followed by the tag text.

A tag may contain spaces, commas, and other Unicode text because tags are
added one at a time. Leading and trailing spaces are removed. An exact
duplicate is ignored. Comparison is case-sensitive: `Wien` and `wien` are two
tags. Order is preserved.

There is no separate place field and no separate region field. Older
collections that had those values keep them as tags after the schema 6
upgrade described in [Upgrades and database migrations](#upgrades-and-database-migrations).

As you type in **New tag**, the page lists existing tags that start with what you typed. The list is labeled **Tag suggestions**. Suggestions come from tags already used in the collection. Tags already on this postcard are omitted. A tag that no postcard has yet is still allowed: type it and press Enter, or choose **Add tag**.

Matching ignores letter case, but the stored spelling is kept. Exact-case matches are listed first, so typing `wien` can suggest the existing tag `Wien`.

| Action | While suggestions are open |
| --- | --- |
| Tab | Adds the highlighted suggestion, or the first suggestion if none is highlighted, and stays in **New tag**. |
| Down Arrow or Up Arrow | Moves through the suggestions. |
| Enter | Adds the highlighted suggestion. If none is highlighted, Enter adds the text you typed and does not save the postcard. |
| Escape | Closes the list without adding a tag. |
| Click or tap a suggestion | Adds that tag. Leaving the suggestion before release does not add it. |

Shift+Tab, and Tab when no list is open, move focus normally. While an input method is composing text, these keys do not accept a suggestion early.

The page says **Tag {tag} added.** when a suggestion is accepted. It says **1 tag suggestion available.** or **{count} tag suggestions available.** when the number of suggestions changes.

The Browse tag filter matches whole tags exactly. The search box matches tag text as part of a broader text search. A location moved into tags by the schema 6 upgrade remains findable in both ways.

## Export and import JSON

JSON export is a portable copy of the records. It is not a complete backup,
because it does not contain image bytes. For a restorable copy of the
collection, use [Back up the collection](#back-up-the-collection).

### Download the records

1. Choose **Import / Export**.
2. Under **Export**, choose **Download database as JSON**.

The file name is `postcards-export.json`. The current file uses schema
version 6. Each postcard includes its numeric ID, share UUID, front and back
paths, year, description, tags, and created/updated timestamps. It does not
include separate place or region fields.

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

> **Caution:** **Replace all existing postcards** asks **Replace ALL existing postcards?**
> The confirmation button is **Replace**. This removes every
> current record even when the file is empty. It does not delete image files.
> Back up `/data`, or the direct-run `data/` directory, before replacing.

A successful import says how many postcards were imported. If any record in
the file is invalid, the whole import is cancelled and the previous records
remain. The page reports the first failing record.

Compatibility rules:

| File | What the current application does |
| --- | --- |
| Schema version 6 export | Imports as exported. Unknown fields are rejected. |
| Schema versions 1 through 5 | Still accepted. Missing tags become an empty list. |
| Older `title` and `notes` values | Versions 1 through 4 merge non-empty values into the description, in that order, separated by one blank line. The original text is not trimmed. |
| Older place and region values | Versions 1 through 5 convert non-blank values into tags, place before region, without adding an exact duplicate. |
| A current file, or a file with no schema version, that still contains place, region, title, or notes | Rejected, so those values are not silently dropped. |
| A version newer than 6 | Rejected. |

An older record with an empty front path can be imported and remains empty
until you edit it and supply a front image.

Return to **Browse** after an import to refresh the filter lists.

## Run the application day to day

### Find the installed version

Every page has a footer. When the version loads, it reads **Version** followed
by the running version string. The label pattern is `Version {version}`.

| How you started it | Footer value |
| --- | --- |
| Published release image | The release version without a leading `v` |
| Local Compose build, unless you set `PPM_VERSION` | `dev` |
| `python3 -m app`, unless you set `PPM_VERSION` | `dev` |
| `PPM_VERSION` set to a blank, non-printable, or overlong value | `dev` |

You can also request the same value:

```sh
curl -fsS http://127.0.0.1:8000/api/version
```

A healthy response is JSON with a `version` field and a `Cache-Control:
no-cache` header. If the footer stays empty, the page itself can still work;
the version request failed. Check the application log.

The footer is the version to compare with a backup and with a release. Do not
use a number written into an old copy of this guide.

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

To update a Compose checkout:

1. Back up `/data` first. Do this before any upgrade that might migrate the
   database.
2. Update the checkout with a fast-forward pull.
3. Rebuild and check health.

```sh
git pull --ff-only
docker compose up -d --build
docker compose ps
```

For a published image, back up first, then pull the new tag and recreate the
container with the same volume. Do not switch the volume name while updating.

### Upgrades and database migrations

The application migrates an older database automatically the first time the
new version opens it. The migration runs in one transaction. If it fails, the
previous database is left unchanged and the application does not finish
starting. A database that is already at the current schema is not modified
again.

The current database schema is version 6. These are data-schema versions, not
release numbers.

| Schema | What changed for existing records |
| --- | --- |
| 1 | Canonical postcard fields are added when missing. |
| 2 | Tags are added. Existing records get an empty tag list. |
| 4 | Each postcard receives a random share UUID. IDs, images, and timestamps stay the same. |
| 5 | Older title and notes text is merged into the description, then those columns are removed. |
| 6 | Non-blank former place and region values become tags, then those columns are removed. |

Schema 6 appends the former place before the former region. It trims
surrounding whitespace, skips blank values, and does not add a tag that the
postcard already has exactly. `Wien` and `wien` both remain if both existed,
because tag comparison is case-sensitive. IDs, share UUIDs, image paths, year,
description, timestamps, and the sequence used for future IDs are preserved.

> **Warning:** After schema 6 has been written, an older application version
> will refuse the database. Downgrading is not supported. Keep the backup made
> before the upgrade, together with a note of the application version that
> created it, if you may need to return to that version.

If a stored tag list is corrupt, schema 6 stops instead of guessing. The
startup error names the postcard ID, the migration rolls back, and the older
database remains. Restore the pre-upgrade backup or repair that record before
trying the upgrade again. Do not delete the database to force startup.

### Move an old `./data` directory into the Compose volume

Older Compose files stored Docker data in the checkout's `./data` directory.
Current Compose uses the named volume. This one-time copy refuses to overwrite
a volume that already contains files and does not delete `./data`:

```sh
docker compose down &&
  docker compose run --rm --no-deps -v "$PWD/data:/legacy:ro" app \
    sh -c 'if [ -n "$(ls -A /data)" ]; then
        echo "volume is not empty; not migrating" >&2; exit 1
      fi && cp -a /legacy/. /data/' &&
  docker compose up -d --build
```

If the volume is not empty, nothing is copied and the application stays
stopped. Start it again with `docker compose up -d` only after you have
decided which copy is authoritative. Check the records and images before
removing the old directory yourself.

### Permissions and the non-root container

The container runs as `ppm`, not as root. A new named volume is writable
without extra steps. Check a running stack:

```sh
docker compose exec app id
docker compose exec app sh -c 'touch /data/.write-test && rm /data/.write-test && echo /data is writable'
```

The first command should show uid 1000 and the user `ppm`, not uid 0.

A volume created by an older root container can be owned by root. After an
upgrade the log may show a database or directory error, including `attempt to
write a readonly database`. Back up first, then correct ownership once:

```sh
docker compose stop &&
  docker compose run --rm --no-deps --user 0 app \
    chown -R 1000:1000 /data &&
  docker compose up -d --build
```

Use your configured user and group ids instead of `1000:1000` if you changed
`PPM_UID` and `PPM_GID`. This changes ownership only. It does not rename or
rewrite postcard files. The one-off container is the only root step; the
running application stays unprivileged.

On a Linux bind mount owned by another account, build with matching ids
instead of changing the application user at runtime:

```sh
PPM_UID="$(id -u)" PPM_GID="$(id -g)" docker compose up -d --build
```

## Back up and restore

> **Warning:** Stop the application before copying or restoring `/data`.
> Copying a live SQLite database can capture a partial write. JSON export does
> not include image bytes, so it cannot restore the pictures.

A complete backup is an archive of `/data`: `postcards.db`, any SQLite sidecar
files, and `images/`. The `images/thumbs/` cache is optional.

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

The listing should include `./postcards.db` and `./images/`. If the archive
command fails, the application stays stopped. Fix the error, then run
`docker compose start`.

Copy the archive somewhere outside the application directory. Treat it as
private: it contains the collection and the images.

For a direct Python install, stop `python3 -m app`, then archive the database
file and the image directory with the same care. Do not copy only the database.

### Restore a backup

> **Caution:** A restore replaces the current `/data` contents. Extracting an
> archive over existing files can mix old images or database journal files
> with the snapshot. The commands below first archive the current volume, then
> empty `/data`, then extract the selected backup.

Inspect the archive before restoring it. Put it in `backups/` and set
`backup` to its file name:

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
with that database. A current backup opened by an older version can be
rejected after schema 6.

## Restrict network access

### What the application protects by itself

The default Compose and `docker run` examples bind to `127.0.0.1`. That is
the access control for a single computer: other machines cannot open the port.

The application has no login of its own. It serves the browser interface, the
API, and `/images/` over plain HTTP. It does not treat proxy forwarding
headers as authentication. A share UUID does not restrict listing, editing, or
deleting.

> **Warning:** Do not publish port 8000 on a public or shared network without
> a proxy that requires authentication. Anyone who can reach the port can read,
> change, and delete the collection.

### Add the Caddy proxy

`compose.proxy.yaml` adds Caddy 2.10 in front of the application. Caddy
terminates TLS and requires HTTP Basic Authentication for the whole site: the
pages, every API path, and `/images/`. With the overlay, the application port
is no longer published. Caddy is the only entry point, on ports 80 and 443.

`docker compose up` without the overlay file does not start the proxy and does
not change the loopback-only behavior.

1. Create a local environment file from the example:

   ```sh
   cp .env.example .env
   ```

2. Generate a password hash. Replace the sample password before running it:

   ```sh
   docker run --rm caddy:2.10 caddy hash-password --plaintext 'your-password'
   ```

3. Edit `.env`, which is ignored by Git:
   - Set `PPM_PROXY_USER` to the login name.
   - Set `PPM_PROXY_PASSWORD_HASH` to the generated hash, wrapped in single
     quotes. An unquoted hash is corrupted because `$` is treated as a
     variable reference.
   - Set `PPM_PROXY_HOST` to `localhost` or to the public host name browsers
     will use.

   A placeholder hash is not usable. It must be the hash just generated:

   ```sh
   PPM_PROXY_PASSWORD_HASH='$2a$14$replace-with-the-generated-hash'
   ```

4. Start both files:

   ```sh
   docker compose -f compose.yaml -f compose.proxy.yaml up -d --build
   ```

5. Open `https://localhost` and sign in with the user name and the password
   you hashed. Do not put that password in the repository.

TLS depends on `PPM_PROXY_HOST`:

| Host value | Certificate |
| --- | --- |
| `localhost` (default) | Caddy's internal certificate authority. Browsers warn until that authority is trusted. Suitable for local or lab use. |
| A public host name that points at this machine, with ports 80 and 443 reachable | A publicly trusted certificate, requested and renewed by Caddy. |

Stop the proxied stack with the same file list:

```sh
docker compose -f compose.yaml -f compose.proxy.yaml down
```

Backup and restore commands stay the same. They do not need the proxy file.

The container health check still calls the application directly inside the
`app` container. It does not use the proxy login. From another computer, the
health and version URLs require the same Basic Authentication as the rest of
the site.

### Limits of the proxy

Basic Authentication encrypts the password only because TLS is in front of it.
Do not send the same credentials to an `http://` address.

The proxy does not provide personal accounts, permission levels, or an audit
log. Everyone who knows the one user name and password can change the
collection. Anyone with shell or Docker access on the host can still read the
volume and reach the application container directly. A forwarded share link
still requires that login, but the login is shared, not per recipient.

## Privacy and security

- The collection stays on the computer or server where you installed the
  application. The application does not send postcards to a hosted account
  service.
- Browser storage on each visitor's computer remembers only the interface
  language, sort, and filters. It does not store postcard text or images.
- Uploaded files are renamed to random generated names. The original file name
  is not kept.
- Share links are unguessable addresses, not authorization.
- Without the proxy, network reachability is the only boundary. With the
  proxy, the shared password and TLS are the boundary, and host access
  bypasses both.
- Backups and JSON exports are copies of the collection. Store them where you
  would store the photographs themselves, not in a public directory or a Git
  checkout.
- `.env` holds the proxy login hash. Never commit it. The example file
  contains placeholders only.
- Logs can contain operational errors. They are not a place to paste passwords
  or backup archives.
- The image responses are sent with `nosniff` and a restrictive content
  security policy so a stored file is not treated as an active page.

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

Through the Caddy proxy, add the proxy login to `curl` and use the HTTPS
address. A failed database check returns HTTP 503 and
`{"status": "error", "error": "database unavailable"}`.

For the proxy container:

```sh
docker compose -f compose.yaml -f compose.proxy.yaml logs --tail=100 proxy
```

| What you see | What it usually means | What to do |
| --- | --- | --- |
| Browser cannot open `127.0.0.1:8000` | The container is stopped, Docker is not running, or the host port is not 8000 | Run `docker compose ps`. Start Docker. Check `PPM_PORT`. |
| `app` is not healthy | Startup failed, often while creating or migrating `/data` | Read `docker compose logs --tail=100 app`. Do not delete the volume. |
| `attempt to write a readonly database` | `/data` is owned by root, or the mount cannot be written by `ppm` | Follow [Permissions and the non-root container](#permissions-and-the-non-root-container) after a backup. |
| `unsupported database schema version` | The database was written by a newer application than the one you started | Stop and run the version that created it, or restore a backup made by this version. Do not downgrade past schema 6. |
| Startup names a postcard and says its tags are corrupt | Schema 6 refused to guess | The previous database is unchanged. Restore the pre-upgrade backup, or repair that record before upgrading again. |
| Proxy starts but the browser warns about the certificate | `PPM_PROXY_HOST` is `localhost`, so the certificate is from Caddy's local authority | Trust that authority for lab use, or set a real public host name. |
| Proxy returns no site and Compose says a variable is missing | `.env` does not set `PPM_PROXY_USER` or `PPM_PROXY_PASSWORD_HASH` | Copy `.env.example` and set both. Quote the hash. |
| Login is rejected | The hash was unquoted, or the password differs from the hashed one | Generate the hash again and wrap it in single quotes. |
| Footer has no version | `/api/version` failed | The rest of the page can still work. Check the application log and the proxy login. |
| **Image unavailable** | The stored path is not a same-origin image address, or the file is missing | Edit the postcard and upload the image again, or restore `images/` from backup. |
| Upload says the image is too large or unsupported | The file is over 20 MiB, empty, or not a PNG, JPEG, GIF, or WebP | Choose a supported file. The previous path remains. |
| Import reports an unsupported field or version | The file is newer than this application, or a current file still has removed fields | Import it with the application that created it, or remove obsolete fields only in a copy whose schema version you understand. A failed import keeps the current records. |
| **No postcards yet.** after you know records exist | Search or filters exclude every row | Clear **Search…** and choose **Reset filters**. |
| Cleanup says the database was not found | The command ran outside the container or against the wrong path | Use `docker compose exec app python -m app.cleanup` for Compose. |

Recovery order when startup fails after an upgrade:

1. Leave the volume in place.
2. Read the log and identify whether this is permissions, a newer schema, or a
   failed migration.
3. If you need the previous known-good state, restore the backup taken before
   the upgrade onto an application version compatible with that backup.
4. Do not run `docker compose down -v` as a repair step.

## Configuration reference

Set these only when the default is wrong. Compose does not automatically pass
arbitrary host variables into the container; the published image and Dockerfile
already set the container defaults.

| Variable | Default outside Docker | Docker value | Purpose |
| --- | --- | --- | --- |
| `PPM_HOST` | `127.0.0.1` | `0.0.0.0` inside the container | Interface the application binds to |
| `PPM_PORT` | `8000` | `8000` inside the container | Container listen port. In Compose, the host's `PPM_PORT` selects the published host port only. |
| `PPM_DB_PATH` | `data/postcards.db` | `/data/postcards.db` | SQLite file |
| `PPM_IMAGE_DIR` | `images` next to the database | `/data/images` | Uploaded images |
| `PPM_VERSION` | `dev` when unset | Release version in a published image; `dev` for a default local build | Footer and `/api/version` |
| `PPM_UID`, `PPM_GID` | Not used | `1000` and `1000` | User and group for a rebuilt image |
| `PPM_PROXY_HOST` | Used only with the proxy overlay | `localhost` | Name Caddy serves |
| `PPM_PROXY_USER` | Used only with the proxy overlay | None; required by the overlay | Basic Authentication user |
| `PPM_PROXY_PASSWORD_HASH` | Used only with the proxy overlay | None; required by the overlay | bcrypt hash, single-quoted in `.env` |

Useful operator endpoints, on the application origin:

| Method | Path | Result |
| --- | --- | --- |
| GET | `/api/health` | `{"status": "ok"}` when the server and database respond |
| GET | `/api/version` | `{"version": "..."}` for the footer value |
| GET | `/api/export` | Schema 6 JSON attachment named `postcards-export.json` |
| POST | `/api/import?mode=append` or `mode=replace` | Imports a JSON export |
| GET | `/images/<generated-name>` | One uploaded original |
| GET | `/images/thumbs/<generated-name>` | A thumbnail, or the original when no thumbnail can be made |

Listing, creating, and deleting through the API use the same rules as the
pages. Obsolete `place` and `region` list filters or sort keys return HTTP 400
rather than being ignored.

## Appendix: PDF edition

This appendix tells the later PDF pipeline how to bind this source. It is not
a collector task. The pipeline is not part of this file, and generated PDFs
are not committed to Git.

### Title page

Render one title page before the body:

| Title-page line | Source |
| --- | --- |
| Picture Postcard Manager User Guide | Document title |
| For collectors and operators | Subtitle |
| Application version | The injected `{{VERSION}}`, taken from the validated release tag. Preserve the tag text, including a leading `v` when the tag has one. |
| Generated on | The injected `{{GENERATED_ON}}`, as an ISO-8601 date. |
| Source | `docs/user-guide.md` at that release tag |

Do not read a release version from the body, the Git branch name, or the
default branch at build time. If `{{VERSION}}` is missing, fail the build
instead of writing a fallback release number into the PDF.

### Contents, headings, and links

- Generate the table of contents and PDF bookmarks from heading levels 1
  through 3. Do not maintain a separate contents list in this file.
- Keep heading text selectable and in reading order.
- Keep markdown links to headings as in-document links.
- Build the PDF from this file only. Do not include `docs/research/` or follow a link into it. Research notes are not release-guide content.
- The only external link that needs to survive is the public project site
  <https://github.com/schmidt-software/picture-postcard-manager>. Image names
  and commands are text, not remote images.
- There are no screenshots. A later screenshot must be regenerated from the
  released interface, stored under `docs/assets/`, given a text alternative
  that repeats the relevant UI label, and omitted when it would only duplicate
  a table.

### Callouts

A callout is a blockquote whose first line starts with one of these labels:

| Label | Meaning for the reader | PDF treatment |
| --- | --- | --- |
| **Note:** | Context that prevents a wrong assumption | Informational callout, not color alone |
| **Warning:** | Data loss or exposure is likely if the instruction is skipped | Warning callout with the word Warning |
| **Caution:** | The next action deletes or replaces collection data | Caution callout with the word Caution |

### Asset name

The release asset name is:

`picture-postcard-manager-user-guide-{{VERSION}}.pdf`

`{{VERSION}}` is the same validated release tag injected into the title page.
The pipeline owns pinning the PDF tool, uploading one asset, and failing
visibly when the build fails. This guide only fixes the source, the
placeholders, and the asset-name pattern.
