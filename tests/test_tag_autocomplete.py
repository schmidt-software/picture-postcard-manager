"""Static markup/CSS and optional JavaScript runtime checks for the tag-input
autocomplete (issue #47)."""

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"


class TagAutocompleteUiTest(unittest.TestCase):
    def test_combobox_markup(self):
        html = (STATIC / "index.html").read_text()
        # Accessible combobox pattern on the existing tag input.
        self.assertRegex(html, r'<input id="tag-input"[^>]*\n?[^>]*\n?[^>]*role="combobox"')
        self.assertIn('aria-expanded="false"', html)
        self.assertIn('aria-controls="tag-suggestions"', html)
        self.assertIn('aria-autocomplete="list"', html)
        self.assertRegex(html, r'<ul id="tag-suggestions"[^>]*role="listbox"')
        # The listbox starts hidden and carries a localized label.
        self.assertRegex(html, r'<ul id="tag-suggestions"[^>]*\n?[^>]*hidden>')
        self.assertRegex(html, r'<ul id="tag-suggestions"[^>]*data-i18n-aria-label="tagSuggestions"')
        # Live region for suggestion counts and accepted tags, visually hidden.
        self.assertRegex(
            html, r'<span id="tag-status" class="visually-hidden" role="status" aria-live="polite">')

    def test_autocomplete_css(self):
        css = (STATIC / "style.css").read_text()
        # The dropdown overlays the form instead of being clipped by it.
        self.assertRegex(css, r"\.tag-suggestions \{[^}]*position: absolute")
        self.assertRegex(css, r"\.tag-suggestions \{[^}]*overflow-y: auto")
        # Hover and keyboard-active states are visually distinct.
        self.assertIn(".tag-option:hover", css)
        self.assertIn(".tag-option.active", css)
        # Forced-colors mode keeps list, hover and active option visible.
        self.assertRegex(
            css, r"forced-colors: active[^@]*\.tag-suggestions \{[^}]*CanvasText")
        self.assertRegex(
            css, r"forced-colors: active[^@]*\.tag-option\.active \{[^}]*Highlight")
        # Narrow screens keep a usable, scrollable list.
        self.assertRegex(css, r"max-width: 480px[^@]*\.tag-suggestions \{[^}]*max-height")
        # The live region helper exists.
        self.assertRegex(css, r"\.visually-hidden \{[^}]*clip-path")

    def test_translations(self):
        js = (STATIC / "languages.js").read_text()
        for key in ("tagSuggestions:", "tagSuggestionsOne:", "tagSuggestionsMany:",
                    "tagSuggestionAccepted:"):
            self.assertEqual(js.count(key), 2, f"{key} must exist in both languages")

    @unittest.skipUnless(shutil.which("node"), "Node.js is optional")
    def test_autocomplete_runtime(self):
        result = subprocess.run(
            [shutil.which("node"), str(ROOT / "tests" / "tag_autocomplete_runtime.js")],
            cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
