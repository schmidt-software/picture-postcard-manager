"""Regression checks for overview editing and confirmed deletion."""

import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class OverviewActionsTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is optional")
    def test_row_actions_runtime(self):
        result = subprocess.run(
            [shutil.which("node"), str(ROOT / "tests/overview_actions_runtime.js")],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
