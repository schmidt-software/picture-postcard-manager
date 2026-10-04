# Copilot instructions

Project: **Picture Postcard Manager** — management of a picture postcard collection.
Repository: `schmidt-software/picture-postcard-manager`.

## Ground rules

- Communication with the maintainer happens in **German**; everything committed to the
  repository (code, comments, docs, commit messages, PR titles/descriptions) is **English**.
- The app must run both locally (`python3 -m app`) and on a server (Docker) for central access.
- Keep the architecture minimal: Python standard library backend (`http.server`, `sqlite3`),
  plain HTML/CSS/JS frontend, SQLite database. Do not add dependencies without a strong reason.
- Core features: entry form, browse mode, database, JSON export/import.

## Workflow

- The maintainer creates one GitHub issue per detail topic (e.g. input fields).
- Each issue is implemented on its own branch (`<type>/<issue-number>-<short-description>`),
  with atomic commits and a pull request that closes the issue.
- Run `python3 -m unittest discover -s tests -v` before pushing; CI runs the same command.
- Follow the conventions in `CONTRIBUTING.md`.
