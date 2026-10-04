"""Static and optional JavaScript runtime checks for the image upload controls."""

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"


class ImageUploadUiTest(unittest.TestCase):
    def test_picker_markup(self):
        html = (STATIC / "index.html").read_text()
        for side in ("front", "back"):
            self.assertIn(f'id="choose-{side}-image"', html)
            self.assertRegex(
                html,
                rf'<input type="file" id="{side}-image-file" '
                r'accept="image/png,image/jpeg,image/gif,image/webp" hidden>',
            )
        self.assertIn('<button type="submit" id="save"', html)

    @unittest.skipUnless(shutil.which("node"), "Node.js is optional")
    def test_javascript_runtime(self):
        result = subprocess.run(
            [shutil.which("node"), str(ROOT / "tests" / "image_runtime.js")],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
