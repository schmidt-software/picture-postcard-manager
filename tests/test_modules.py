"""Regression checks for the ES module structure of the frontend."""

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"


def run_node(*args, cwd=ROOT):
    return subprocess.run(
        [shutil.which("node"), *map(str, args)],
        cwd=cwd, capture_output=True, text=True, timeout=30,
    )


class ModuleStructureTest(unittest.TestCase):
    def test_app_js_is_loaded_as_module(self):
        html = (STATIC / "index.html").read_text()
        self.assertIn('<script type="module" src="/app.js"></script>', html)
        self.assertIn('<script src="/languages.js"></script>', html)

    def test_modules_exist_and_import_only_local_files(self):
        modules = sorted((STATIC / "js").glob("*.js"))
        self.assertGreaterEqual(len(modules), 8)
        for file in [STATIC / "app.js", *modules]:
            source = file.read_text()
            for specifier in re.findall(r'^import .* from "(.*)";$', source, re.M):
                self.assertTrue(specifier.startswith("./"), f"{file.name}: {specifier}")
                resolved = (file.parent / specifier).resolve()
                self.assertTrue(resolved.is_file(), f"{file.name} imports missing {specifier}")

    def test_bundle_lists_every_module(self):
        bundle = (ROOT / "tests" / "bundle.js").read_text()
        for file in (STATIC / "js").glob("*.js"):
            self.assertIn(f"js/{file.name}", bundle,
                          f"tests/bundle.js must list js/{file.name}")

    @unittest.skipUnless(shutil.which("node"), "Node.js is optional")
    def test_module_graph_links(self):
        result = run_node("--experimental-vm-modules", ROOT / "tests/modules_check.js")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node.js is optional")
    def test_module_graph_is_acyclic(self):
        result = run_node(ROOT / "tests/cycles_check.js")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("acyclic", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "Node.js is optional")
    def test_cycle_check_detects_cycles(self):
        # A deliberately introduced two-module cycle must fail the check.
        with tempfile.TemporaryDirectory() as tmp:
            static = Path(tmp) / "static"
            shutil.copytree(STATIC, static)
            dom = static / "js" / "dom.js"
            dom.write_text('import { api } from "./api.js";\n' + dom.read_text())
            api = static / "js" / "api.js"
            api.write_text('import { $ } from "./dom.js";\n' + api.read_text())
            result = run_node(ROOT / "tests/cycles_check.js", static)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Import cycles detected", result.stderr)
            self.assertIn("js/dom.js", result.stderr)


if __name__ == "__main__":
    unittest.main()
