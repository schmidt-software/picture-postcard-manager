# Contributing

## Workflow

1. Every feature or change is described in a GitHub issue.
2. Work happens on a dedicated branch per issue, named `<type>/<issue-number>-<short-description>`
   (e.g. `feature/3-input-fields`, `fix/7-import-error`).
3. Commits are atomic: one logical change per commit, with a descriptive message
   in imperative mood (e.g. `Add date field to postcard schema`).
   Reference the issue in the commit body or PR (e.g. `Refs #3`).
4. Each branch is merged into `main` via a pull request that closes the issue (`Closes #3`).
5. CI (unit tests) must pass before merging.

## Conventions

- Everything in the repository (code, comments, commit messages, documentation,
  issue/PR texts created by contributors) is written in **English**.
- Keep the architecture minimal: no third-party dependencies unless clearly necessary.
  One deliberate exception exists: **Pillow is an optional dependency, only for
  thumbnails** (issue #28). The standard library cannot decode or resize JPEG,
  WebP or GIF, so overview thumbnails need an imaging library. The app must
  always run and pass the default test suite without Pillow — when it is not
  installed, thumbnail generation is disabled and thumbnail URLs serve the
  original images unchanged. Optional dependencies live in
  `requirements-optional.txt`; the Docker image installs them by default and CI
  tests both modes. Code must never require Pillow at import time (`app/thumbs.py`
  guards the import), and Pillow-dependent tests must skip themselves cleanly
  via `unittest.skipUnless`.
- The frontend ES modules under `app/static/js/` must keep an acyclic import
  graph (checked by `tests/cycles_check.js` via `tests/test_modules.py`). Put
  shared primitives in leaf modules and pass callbacks (e.g. route handlers
  into `initRouting`) instead of importing "upward". List every new module in
  `tests/bundle.js` so the runtime tests cover it.
- When adding postcard fields, update the schema in `app/db.py` (`SCHEMA`, `EDITABLE_FIELDS`,
  and a migration via `PRAGMA user_version`), the UI in `app/static/`, the tests, and the README.
- Database changes must keep JSON export/import working; bump `schema_version` when the export format changes.
- Schema history: version 5 removed the legacy `title` and `notes` fields; their content
  is merged into `description` on migration and on imports of versions 1-4 (see the README).
  Version 6 removed the `place` and `region` fields; their non-blank values become tags
  on migration and on imports of versions 1-5 (see the README).
- A user-visible behavior, label, command, configuration, or deployment change updates
  `docs/user-guide.md` in the same pull request. Do not hard-code a release version in
  that file; the PDF pipeline injects `{{VERSION}}` and `{{GENERATED_ON}}`.
