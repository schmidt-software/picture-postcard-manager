"""Server-side checks for free-form year values (issue #65).

The exactly-four-digit restriction introduced by #60 is removed: year is
optional free-form text, stored verbatim across create, update, import and
export. Distinct values feed the suggestion list via filter_values().
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from app.db import Database

ROOT = Path(__file__).resolve().parents[1]


class YearFreeFormTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "postcards.db")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def postcard(self, year):
        return {"front_image_path": "/front.jpg", "year": year}

    def test_accepts_free_form_text_verbatim(self):
        # Regression for the #60 four-digit-only rule: all of these are valid.
        for year in ("", None, "1927", "around 1800", "ca. 1960", "unknown",
                     "1910-1920", " 1908 ", "１９０８", "١٩٠٨", 1908):
            with self.subTest(year=year):
                created = self.db.create(self.postcard(year))
                self.assertEqual(created["year"], "" if year is None else str(year))

    def test_rejects_non_string_non_int_year(self):
        for year in (False, [], {}, 19.08):
            with self.subTest(year=year):
                with self.assertRaisesRegex(ValueError, "string or null"):
                    self.db.create(self.postcard(year))

    def test_update_stores_free_text_verbatim(self):
        card = self.db.create(self.postcard("1908"))
        updated = self.db.update(card["id"], {"year": "ca. 1910"})
        self.assertEqual(updated["year"], "ca. 1910")

    def test_import_accepts_free_text_years(self):
        payload = {"postcards": [self.postcard("ca. 1910"),
                                 self.postcard("unknown")]}
        self.assertEqual(self.db.import_data(payload), 2)
        self.assertEqual({p["year"] for p in self.db.list()},
                         {"ca. 1910", "unknown"})

    def test_export_reimport_round_trip_preserves_years(self):
        for year in ("1927", "around 1800", "ca. 1960", "unknown", ""):
            self.db.create(self.postcard(year))
        exported = self.db.export_data()
        self.db.import_data(exported, mode="replace")
        self.assertEqual([p["year"] for p in self.db.list()],
                         [p["year"] for p in exported["postcards"]])

    def test_filter_values_lists_distinct_years_without_blanks(self):
        for year in ("ca. 1960", "1927", "1927", "", "unknown"):
            self.db.create(self.postcard(year))
        values = self.db.filter_values()["year"]
        self.assertEqual(sorted(values), sorted({"ca. 1960", "1927", "unknown"}))

    def test_year_filter_matches_free_text_exactly(self):
        self.db.create(self.postcard("ca. 1960"))
        self.db.create(self.postcard("1960"))
        rows = self.db.list(filters={"year": "ca. 1960"})
        self.assertEqual([r["year"] for r in rows], ["ca. 1960"])


class YearComboboxUiContractTest(unittest.TestCase):
    def test_editable_combobox_markup(self):
        html = Path("app/static/index.html").read_text()
        # Accessible editable combobox on the year input.
        self.assertRegex(html, r'<input id="year-input" name="year"[^>]*\n?[^>]*\n?[^>]*role="combobox"')
        self.assertIn('aria-controls="year-suggestions"', html)
        self.assertRegex(html, r'<ul id="year-suggestions"[^>]*role="listbox"')
        self.assertRegex(html, r'<ul id="year-suggestions"[^>]*data-i18n-aria-label="yearSuggestions"')
        self.assertRegex(
            html, r'<span id="year-status" class="visually-hidden" role="status" aria-live="polite">')
        # The #60 restrictive input attributes and error alert are gone.
        self.assertNotIn('pattern="[0-9]{4}"', html)
        self.assertNotIn('maxlength="4"', html)
        self.assertNotIn('id="year-error"', html)

    def test_no_client_side_four_digit_validation(self):
        form = Path("app/static/js/form.js").read_text()
        self.assertNotIn("[0-9]{4}", form)
        self.assertNotIn("invalidYear", form)
        feedback = Path("app/static/js/feedback.js").read_text()
        self.assertNotIn("year-error", feedback)

    def test_translations(self):
        languages = Path("app/static/languages.js").read_text()
        for key in ("yearSuggestions:", "yearSuggestionsOne:",
                    "yearSuggestionsMany:", "yearSuggestionAccepted:"):
            self.assertEqual(languages.count(key), 2,
                             f"{key} must exist in both languages")
        self.assertNotIn("invalidYear:", languages)
        self.assertNotIn("errorYearFormat:", languages)

    def test_no_server_side_four_digit_rule(self):
        db = Path("app/db.py").read_text()
        self.assertNotIn("exactly four digits", db)
        self.assertNotIn("allow_legacy_year", db)

    def test_combobox_css(self):
        css = Path("app/static/style.css").read_text()
        # The year combobox reuses the tag suggestion styles: overlay,
        # scrolling, distinct hover/active, forced-colors and narrow-screen
        # behavior are all covered by the shared classes.
        html = Path("app/static/index.html").read_text()
        self.assertIn('id="year-suggestions" class="tag-suggestions"', html)
        self.assertRegex(css, r"forced-colors: active[^@]*\.tag-option\.active \{[^}]*Highlight")
        self.assertRegex(css, r"max-width: 480px[^@]*\.tag-suggestions \{[^}]*max-height")

    @unittest.skipUnless(shutil.which("node"), "Node.js is optional")
    def test_year_combobox_runtime(self):
        result = subprocess.run(
            [shutil.which("node"), str(ROOT / "tests" / "year_combobox_runtime.js")],
            cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
