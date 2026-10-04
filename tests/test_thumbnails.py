"""Regression checks for compact image previews."""

import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class OverviewParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.headers = []
        self.fields = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "th":
            self.headers.append(attrs.get("data-i18n"))
        if tag in ("input", "textarea") and "name" in attrs:
            self.fields.append(attrs["name"])


class ThumbnailTest(unittest.TestCase):
    def test_overview_columns_do_not_remove_form_fields(self):
        parser = OverviewParser()
        parser.feed((ROOT / "app/static/index.html").read_text())
        self.assertIn("frontImage", parser.headers)
        self.assertIn("backImage", parser.headers)
        for key in ("frontImagePath", "backImagePath", "region", "description"):
            self.assertNotIn(key, parser.headers)
        for field in ("front_image_path", "back_image_path", "region", "description"):
            self.assertIn(field, parser.fields)

    @unittest.skipUnless(shutil.which("node"), "Node.js is optional")
    def test_javascript_runtime(self):
        result = subprocess.run(
            [shutil.which("node"), str(ROOT / "tests/thumbnails_runtime.js")],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
