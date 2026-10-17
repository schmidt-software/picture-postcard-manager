"""Checks that the MIT license is present, intact, and shipped (Refs #61).

The project is MIT licensed. These tests guard the acceptance criteria of
issue #61: the official license text is not accidentally modified, the README
and container metadata identify the license, and release/container artifacts
include the license file.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LICENSE = ROOT / "LICENSE"

# Official MIT License text (SPDX / OSI wording), with the copyright line
# checked separately below.
MIT_BODY = """Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE."""


class LicenseFileTest(unittest.TestCase):
    def setUp(self):
        self.text = LICENSE.read_text(encoding="utf-8")

    def test_license_file_exists_at_repo_root(self):
        self.assertTrue(LICENSE.is_file())

    def test_starts_with_mit_license_title(self):
        self.assertEqual(self.text.splitlines()[0], "MIT License")

    def test_copyright_line_names_holder_and_year(self):
        self.assertRegex(
            self.text,
            re.compile(r"^Copyright \(c\) 20\d\d Michael Schmidt$", re.M),
            msg="LICENSE must contain the standard copyright line",
        )

    def test_body_matches_official_mit_text_verbatim(self):
        # Normalize only line wrapping differences are NOT allowed: the body
        # must appear verbatim so GitHub's licensee detection matches MIT.
        self.assertIn(MIT_BODY, self.text)


class LicenseMetadataTest(unittest.TestCase):
    def test_readme_identifies_mit_license_and_links_file(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("## License", readme)
        self.assertIn("[MIT License](LICENSE)", readme)
        self.assertIn("`MIT`", readme)

    def test_dockerfile_copies_license_into_image(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertRegex(dockerfile, r"(?m)^COPY LICENSE ")
        self.assertIn('org.opencontainers.image.licenses="MIT"', dockerfile)

    def test_dockerignore_allowlists_license(self):
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        self.assertIn("!LICENSE", dockerignore.splitlines())

    def test_release_image_workflow_sets_license_label(self):
        workflow = (
            ROOT / ".github" / "workflows" / "release-image.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("org.opencontainers.image.licenses=MIT", workflow)


if __name__ == "__main__":
    unittest.main()
