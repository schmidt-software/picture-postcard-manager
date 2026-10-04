"""Dependency-free checks for UI translation coverage and optional JS behavior."""

import re
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"


class InterfaceParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []
        self.stack = []
        self.untranslated = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.elements.append((tag, attrs))
        if tag not in {"meta", "link", "input"}:
            self.stack.append((tag, attrs))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if data.strip() and self.stack:
            if not any("data-i18n" in attrs for _, attrs in self.stack):
                self.untranslated.append(data.strip())


class LocalizationTest(unittest.TestCase):
    def setUp(self):
        self.html = InterfaceParser()
        self.html.feed((STATIC / "index.html").read_text())
        source = (STATIC / "languages.js").read_text()
        self.resources = {}
        for code, block in re.findall(r"^  (\w+): \{\n(.*?)^  \},", source, re.M | re.S):
            self.resources[code] = dict(re.findall(r'^    (\w+): "(.*)",$', block, re.M))

    def test_translation_coverage(self):
        english = self.resources["en"]
        self.assertTrue(english)
        self.assertEqual(set(english), set(self.resources["de"]))
        for key, value in english.items():
            self.assertEqual(
                re.findall(r"\{\w+\}", value),
                re.findall(r"\{\w+\}", self.resources["de"][key]),
                key,
            )
        for _, attrs in self.html.elements:
            for attr in ("data-i18n", "data-i18n-placeholder", "data-i18n-aria-label"):
                if attr in attrs:
                    self.assertIn(attrs[attr], english)
        self.assertEqual(self.html.untranslated, [])
        scripts = [attrs["src"] for tag, attrs in self.html.elements if tag == "script"]
        self.assertEqual(scripts, ["/languages.js", "/app.js"])

    def test_language_independent_validation_and_file_picker(self):
        forms = [attrs for tag, attrs in self.html.elements
                 if tag == "form" and attrs.get("id") in ("postcard-form", "import-form")]
        self.assertEqual(len(forms), 2)
        self.assertTrue(all("novalidate" in form for form in forms))
        file_input = next(attrs for tag, attrs in self.html.elements
                          if tag == "input" and attrs.get("type") == "file")
        self.assertIn("hidden", file_input)
        required = next(attrs for tag, attrs in self.html.elements
                        if tag == "input" and "required" in attrs)
        for error_id in (required["aria-describedby"], "file-error"):
            attrs = next(attrs for _, attrs in self.html.elements if attrs.get("id") == error_id)
            self.assertEqual(attrs["role"], "alert")
        source = (STATIC / "app.js").read_text()
        self.assertNotRegex(source, r"\b(?:confirm|alert|reportValidity)\(")

    @unittest.skipUnless(shutil.which("node"), "Node.js is optional")
    def test_javascript_runtime(self):
        result = subprocess.run(
            [shutil.which("node"), str(ROOT / "tests" / "i18n_runtime.js")],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
