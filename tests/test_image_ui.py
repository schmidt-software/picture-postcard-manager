"""Static and optional JavaScript runtime checks for the form image pickers."""

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"


class ImagePickerUiTest(unittest.TestCase):
    def test_picker_markup(self):
        html = (STATIC / "index.html").read_text()
        for side in ("front", "back"):
            # The whole picker area is a real button: native click, tap,
            # Enter/Space and focus semantics.
            self.assertRegex(
                html,
                rf'<button type="button" id="{side}-image-control"[^>]*class="image-control"',
            )
            self.assertRegex(
                html,
                rf'<input type="file" id="{side}-image-file" '
                r'accept="image/png,image/jpeg,image/gif,image/webp" hidden>',
            )
            # The stored path is internal state only: a hidden input, never a
            # visible or editable text field.
            self.assertIn(f'<input type="hidden" name="{side}_image_path">', html)
            self.assertNotRegex(html, rf'<input name="{side}_image_path"')
            # The trash button is labeled, not color-only (icon + aria-label).
            self.assertRegex(
                html,
                rf'id="{side}-image-clear"[^>]*\n?[^>]*data-i18n-aria-label="remove'
                rf'{side.capitalize()}Image"',
            )
        self.assertIn('<button type="submit" id="save"', html)

    def test_picker_css(self):
        css = (STATIC / "style.css").read_text()
        # Visible focus indication for both picker buttons.
        self.assertIn(".image-control:focus-visible", css)
        self.assertIn(".image-clear:focus-visible", css)
        # Adequate touch target for the trash button.
        self.assertRegex(css, r"\.image-clear \{[^}]*min-width: 44px")
        self.assertRegex(css, r"\.image-clear \{[^}]*min-height: 44px")
        # Forced-colors mode keeps the controls visible.
        self.assertIn(".image-control, .image-clear { border: 1px solid ButtonText; }", css)

    @unittest.skipUnless(shutil.which("node"), "Node.js is optional")
    def test_javascript_runtime(self):
        result = subprocess.run(
            [shutil.which("node"), str(ROOT / "tests" / "image_runtime.js")],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
