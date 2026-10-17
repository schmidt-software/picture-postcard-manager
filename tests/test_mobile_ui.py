import re
import unittest
from pathlib import Path


class MobileUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = Path("app/static/index.html").read_text()
        cls.css = Path("app/static/style.css").read_text()
        cls.overview = Path("app/static/js/overview.js").read_text()

    def test_viewport_and_safe_areas(self):
        self.assertIn("viewport-fit=cover", self.html)
        for inset in ("safe-area-inset-left", "safe-area-inset-right", "safe-area-inset-bottom"):
            self.assertIn(inset, self.css)

    def test_touch_and_keyboard_contract(self):
        self.assertRegex(self.css, r"button\s*\{[^}]*min-height:\s*44px")
        self.assertRegex(self.css, r"input, textarea, select\s*\{[^}]*font-size:[^;]*16px")
        self.assertIn("scroll-margin-block", self.css)
        self.assertIn("prefers-reduced-motion: reduce", self.css)

    def test_phone_card_layout_has_no_table_scroller(self):
        block = re.search(r"@media \(max-width: 700px\) \{(.+?)\n\}", self.css, re.S)
        self.assertIsNotNone(block)
        text = block.group(1)
        self.assertIn(".table-wrap { overflow-x: visible; }", text)
        self.assertIn("tbody tr { display: block", text)
        self.assertIn("content: attr(data-label)", text)

    def test_every_overview_column_gets_a_localized_label(self):
        for key in ("id", "frontImage", "backImage", "tags", "updated", "rowActions"):
            self.assertIn(f'translate("{key}")', self.overview)
        self.assertIn('td.dataset.label = translate(field)', self.overview)
        self.assertGreaterEqual(self.overview.count("dataset.label"), 7)

    def test_mobile_viewports_are_documented(self):
        guide = Path("docs/user-guide.md").read_text()
        self.assertIn("designed for touch from 320 px wide", guide)
        self.assertIn("photo library or camera", guide)
