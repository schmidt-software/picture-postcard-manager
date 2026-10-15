"""Regression checks for the bulk image import."""

import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BulkFormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.file_input = None
        self.error = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id") == "bulk-files":
            self.file_input = attrs
        if attrs.get("id") == "bulk-error":
            self.error = attrs


class BulkImportTest(unittest.TestCase):
    def test_bulk_form_markup(self):
        parser = BulkFormParser()
        parser.feed((ROOT / "app/static/index.html").read_text())
        self.assertIsNotNone(parser.file_input)
        self.assertIn("multiple", parser.file_input)
        self.assertIn("hidden", parser.file_input)
        self.assertEqual(parser.file_input["accept"],
                         "image/png,image/jpeg,image/gif,image/webp")
        self.assertEqual(parser.error["role"], "alert")

    @unittest.skipUnless(shutil.which("node"), "Node.js is optional")
    def test_javascript_runtime(self):
        result = subprocess.run(
            [shutil.which("node"), str(ROOT / "tests/bulk_import_runtime.js")],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
