"""Consistency checks for the end-user guide source.

These checks belong to the guide's content: visible labels, routes, commands,
and version placeholders must keep matching the application. They do not build
a PDF or upload a release asset.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs" / "user-guide.md"
INDEX = ROOT / "app" / "static" / "index.html"
LANGUAGES = ROOT / "app" / "static" / "languages.js"

REQUIRED_HEADINGS = (
    "# Picture Postcard Manager User Guide",
    "## About this edition",
    "## What the application is for",
    "## Before you start",
    "## Install with Docker Compose",
    "## First start and stored data",
    "## Everyday collection tasks",
    "### Create a postcard",
    "### Edit a postcard",
    "### View a postcard",
    "### Share a postcard",
    "### Filter, sort, and page through Browse",
    "### Delete a postcard",
    "## Images",
    "### Overview thumbnails and Pillow",
    "### Add many images at once",
    "### Remove unreferenced images",
    "## Tags and search",
    "## Export and import JSON",
    "## Run the application day to day",
    "### Find the installed version",
    "### Upgrades and database migrations",
    "## Back up and restore",
    "## Restrict network access",
    "## Privacy and security",
    "## Troubleshooting and recovery",
    "## Configuration reference",
    "## Appendix: PDF edition",
)

REQUIRED_SNIPPETS = (
    "docker compose up -d --build",
    "docker compose exec app python -m app.cleanup",
    "python3 -m app.cleanup --delete",
    "ghcr.io/schmidt-software/picture-postcard-manager",
    "caddy:2.10",
    "/api/health",
    "/api/version",
    "/api/export",
    "/api/import?mode=append",
    "postcards-export.json",
    '{"status": "ok"}',
    "PPM_HOST",
    "PPM_PORT",
    "PPM_DB_PATH",
    "PPM_IMAGE_DIR",
    "PPM_VERSION",
    "PPM_PROXY_USER",
    "PPM_PROXY_PASSWORD_HASH",
    "PPM_PROXY_HOST",
    "picture-postcard-manager_postcard-data",
    "picture-postcard-manager-user-guide-{{VERSION}}.pdf",
    "version: \"{{VERSION}}\"",
    "generated_on: \"{{GENERATED_ON}}\"",
    "<!-- refresh-after: #45 -->",
    "<!-- refresh-after: #47 -->",
    "There is no separate place field and no separate region field.",
)

VISIBLE_LABEL_KEYS = (
    "browse",
    "newPostcard",
    "importExport",
    "language",
    "search",
    "sortBy",
    "sortNewest",
    "sortAscending",
    "sortDescending",
    "year",
    "updated",
    "tag",
    "filterAll",
    "resetFilters",
    "id",
    "frontImage",
    "backImage",
    "tags",
    "rowActions",
    "emptyPostcards",
    "loadMore",
    "backToOverview",
    "edit",
    "sharePostcard",
    "shareLink",
    "copyLink",
    "frontImagePath",
    "chooseFrontImage",
    "backImagePath",
    "chooseBackImage",
    "description",
    "newTag",
    "addTag",
    "save",
    "cancel",
    "delete",
    "downloadJson",
    "chooseFile",
    "appendPostcards",
    "replacePostcards",
    "bulkImport",
    "bulkImportHint",
    "chooseImages",
    "bulkStart",
    "confirmDelete",
    "confirmReplace",
    "imageUnavailable",
    "noImage",
    "versionLabel",
    "saved",
)


def _english_labels():
    text = LANGUAGES.read_text(encoding="utf-8")
    start = text.index("en: {")
    end = text.index("de: {", start)
    block = text[start:end]
    return dict(re.findall(r'^    (\w+): "(.*)"' , block, re.M))


class UserGuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guide = GUIDE.read_text(encoding="utf-8")
        cls.labels = _english_labels()

    def test_required_structure_and_commands(self):
        for heading in REQUIRED_HEADINGS:
            self.assertIn(heading, self.guide)
        for snippet in REQUIRED_SNIPPETS:
            self.assertIn(snippet, self.guide)
        self.assertNotRegex(self.guide, r"\bv\d+\.\d+\.\d+\b")
        self.assertNotIn("/Users/", self.guide)
        self.assertNotIn("Closes #49", self.guide)

    def test_visible_english_labels_are_quoted(self):
        missing = [
            key for key in VISIBLE_LABEL_KEYS
            if self.labels[key] not in self.guide
        ]
        self.assertEqual(missing, [])

    def test_current_ui_has_no_place_or_region_controls(self):
        html = INDEX.read_text(encoding="utf-8")
        self.assertNotIn('data-i18n="place"', html)
        self.assertNotIn('data-i18n="region"', html)
        self.assertNotIn("place", self.labels)
        self.assertNotIn("region", self.labels)


if __name__ == "__main__":
    unittest.main()
