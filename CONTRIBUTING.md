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
- When adding postcard fields, update the schema in `app/db.py` (`SCHEMA`, `EDITABLE_FIELDS`,
  and a migration via `PRAGMA user_version`), the UI in `app/static/`, the tests, and the README.
- Database changes must keep JSON export/import working; bump `schema_version` when the export format changes.
