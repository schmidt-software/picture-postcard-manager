import json
import tempfile
import unittest
from pathlib import Path

from app.db import Database


class YearValidationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "postcards.db")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def postcard(self, year):
        return {"front_image_path": "/front.jpg", "year": year}

    def test_accepts_empty_and_exactly_four_ascii_digits(self):
        for year in ("", None, "1908", "2000", "2026", 1908):
            with self.subTest(year=year):
                created = self.db.create(self.postcard(year))
                self.assertEqual(created["year"], "" if year is None else str(year))

    def test_rejects_every_other_year_format_on_create(self):
        for year in ("abc", "19a0", "123", "12345", " 1908 ", "+1908", "19.08", "１９０８", "١٩٠٨", 123):
            with self.subTest(year=year):
                with self.assertRaisesRegex(ValueError, "exactly four digits"):
                    self.db.create(self.postcard(year))

    def test_invalid_update_is_atomic(self):
        card = self.db.create(self.postcard("1908"))
        with self.assertRaisesRegex(ValueError, "exactly four digits"):
            self.db.update(card["id"], {"year": "ca. 1910"})
        self.assertEqual(self.db.get(card["id"])["year"], "1908")

    def test_new_import_records_are_strict(self):
        payload = {"postcards": [self.postcard("ca. 1910")]}
        with self.assertRaisesRegex(ValueError, "exactly four digits"):
            self.db.import_data(payload)
        self.assertEqual(self.db.list(), [])

    def test_full_legacy_exports_preserve_free_text_years(self):
        entry = self.postcard("ca. 1910") | {
            "id": 7,
            "uuid": "11111111-1111-4111-8111-111111111111",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "back_image_path": "", "description": "", "tags": [],
        }
        self.db.import_data({
            "format": "picture-postcard-manager", "schema_version": 6,
            "exported_at": "2026-01-02T00:00:00+00:00", "postcards": [entry],
        }, mode="replace")
        self.assertEqual(self.db.get(7)["year"], "ca. 1910")
        exported = self.db.export_data()
        self.db.import_data(exported, mode="replace")
        self.assertEqual(self.db.get(7)["year"], "ca. 1910")

    def test_synthetic_metadata_cannot_bypass_validation(self):
        entry = self.postcard("ca. 1910") | {
            "id": 7,
            "uuid": "11111111-1111-4111-8111-111111111111",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "back_image_path": "", "description": "", "tags": [],
        }
        for mode, payload in (
            ("append", {"format": "picture-postcard-manager", "schema_version": 6,
                        "exported_at": "2026-01-02T00:00:00+00:00", "postcards": [entry]}),
            ("replace", {"postcards": [entry]}),
        ):
            with self.subTest(mode=mode):
                with self.assertRaisesRegex(ValueError, "exactly four digits"):
                    self.db.import_data(payload, mode=mode)

    def test_mobile_and_accessible_form_contract(self):
        html = Path("app/static/index.html").read_text()
        for fragment in ('inputmode="numeric"', 'maxlength="4"', 'pattern="[0-9]{4}"',
                         'aria-describedby="year-error"', 'id="year-error"', 'role="alert"'):
            self.assertIn(fragment, html)
        form = Path("app/static/js/form.js").read_text()
        self.assertIn('/^[0-9]{4}$/.test(year)', form)
        languages = Path("app/static/languages.js").read_text()
        self.assertIn('invalidYear:', languages)
        self.assertIn('errorYearFormat:', languages)
