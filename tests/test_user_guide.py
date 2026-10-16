"""Consistency checks for the end-user guide source.

These checks belong to the guide's content: visible labels, routes, commands,
and version placeholders must keep matching the application. They do not build
a PDF or upload a release asset.
"""

import ast
import re
import shlex
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs" / "user-guide.md"
INDEX = ROOT / "app" / "static" / "index.html"
LANGUAGES = ROOT / "app" / "static" / "languages.js"

REQUIRED_HEADINGS = (
    "# Picture Postcard Manager User Guide",
    "## About this edition",
    "## What the application is for",
    "## Before you start",
    "## Install with Docker Compose",
    "## First start and stored data",
    "## Everyday collection tasks",
    "### Create a postcard",
    "### Edit a postcard",
    "### View a postcard",
    "### Share a postcard",
    "### Filter, sort, and page through Browse",
    "### Delete a postcard",
    "## Images",
    "### Overview thumbnails and Pillow",
    "### Add many images at once",
    "### Remove unreferenced images",
    "## Tags and search",
    "## Export and import JSON",
    "## Run the application day to day",
    "### Find the installed version",
    "### Upgrades and database migrations",
    "## Back up and restore",
    "## Restrict network access",
    "## Privacy and security",
    "## Troubleshooting and recovery",
    "## Configuration reference",
    "## Appendix: PDF edition",
)

REQUIRED_SNIPPETS = (
    "docker compose up -d --build",
    "docker compose exec app python -m app.cleanup",
    "python3 -m app.cleanup --delete",
    "ghcr.io/schmidt-software/picture-postcard-manager",
    "caddy:2.10",
    "/api/health",
    "/api/version",
    "/api/export",
    "/api/import?mode=append",
    "postcards-export.json",
    '{"status": "ok"}',
    "PPM_HOST",
    "PPM_PORT",
    "PPM_DB_PATH",
    "PPM_IMAGE_DIR",
    "PPM_VERSION",
    "PPM_PROXY_USER",
    "PPM_PROXY_PASSWORD_HASH",
    "PPM_PROXY_HOST",
    "picture-postcard-manager_postcard-data",
    "picture-postcard-manager-user-guide-{{VERSION}}.pdf",
    "version: \"{{VERSION}}\"",
    "generated_on: \"{{GENERATED_ON}}\"",
    "<!-- refresh-after: #45 -->",
    "<!-- refresh-after: #47 -->",
    "There is no separate place field and no separate region field.",
)

VISIBLE_LABEL_KEYS = (
    "browse",
    "newPostcard",
    "importExport",
    "language",
    "search",
    "sortBy",
    "sortNewest",
    "sortAscending",
    "sortDescending",
    "year",
    "updated",
    "tag",
    "filterAll",
    "resetFilters",
    "id",
    "frontImage",
    "backImage",
    "tags",
    "rowActions",
    "emptyPostcards",
    "loadMore",
    "backToOverview",
    "edit",
    "sharePostcard",
    "shareLink",
    "copyLink",
    "frontImagePath",
    "chooseFrontImage",
    "backImagePath",
    "chooseBackImage",
    "description",
    "newTag",
    "addTag",
    "save",
    "cancel",
    "delete",
    "downloadJson",
    "chooseFile",
    "appendPostcards",
    "replacePostcards",
    "bulkImport",
    "bulkImportHint",
    "chooseImages",
    "bulkStart",
    "confirmDelete",
    "confirmReplace",
    "imageUnavailable",
    "noImage",
    "versionLabel",
    "saved",
)


def _english_labels():
    text = LANGUAGES.read_text(encoding="utf-8")
    start = text.index("en: {")
    end = text.index("de: {", start)
    block = text[start:end]
    return dict(re.findall(r'^    (\w+): "(.*)"' , block, re.M))


class UserGuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guide = GUIDE.read_text(encoding="utf-8")
        cls.labels = _english_labels()

    def test_required_structure_and_commands(self):
        for heading in REQUIRED_HEADINGS:
            self.assertIn(heading, self.guide)
        for snippet in REQUIRED_SNIPPETS:
            self.assertIn(snippet, self.guide)
        self.assertNotRegex(self.guide, r"\bv\d+\.\d+\.\d+\b")
        self.assertNotIn("/Users/", self.guide)
        self.assertNotIn("Closes #49", self.guide)

    def test_visible_english_labels_are_quoted(self):
        missing = [
            key for key in VISIBLE_LABEL_KEYS
            if self.labels[key] not in self.guide
        ]
        self.assertEqual(missing, [])

    def test_current_ui_has_no_place_or_region_controls(self):
        html = INDEX.read_text(encoding="utf-8")
        self.assertNotIn('data-i18n="place"', html)
        self.assertNotIn('data-i18n="region"', html)
        self.assertNotIn("place", self.labels)
        self.assertNotIn("region", self.labels)

    def test_commands_use_only_the_version_placeholder(self):
        self.assertNotIn("<release-tag>", self.guide)
        placeholders = set()
        for block in _fenced_blocks(self.guide, "sh"):
            for token in shlex.split(block, comments=False, posix=True):
                placeholders.update(_angle_placeholders(token))
        self.assertEqual(placeholders, {"<version>"})

    def test_proxy_overlay_resets_app_ports_and_exposes_only_http_ports(self):
        overlay = _parse_compose(ROOT / "compose.proxy.yaml")
        app_ports = overlay["services"]["app"]["ports"]
        self.assertEqual(app_ports, {"tag": "!reset", "value": []})
        published = []
        for name, service in overlay["services"].items():
            ports = service.get("ports")
            if isinstance(ports, dict) and ports.get("tag") == "!reset":
                self.assertEqual(ports["value"], [])
                continue
            for mapping in ports or []:
                published.append((name, mapping))
        self.assertEqual(
            [name for name, _mapping in published],
            ["proxy", "proxy"],
        )
        self.assertEqual(
            {_host_port(mapping) for _name, mapping in published},
            {"80", "443"},
        )

    def test_documented_endpoints_match_server_handlers(self):
        handlers = _server_handlers(ROOT / "app" / "server.py")
        samples = {
            "/images/<generated-name>": "/images/sample.jpg",
            "/images/thumbs/<generated-name>": "/images/thumbs/sample.jpg",
        }
        for method, documented in _operator_endpoints(self.guide):
            path, query = _documented_request(documented)
            concrete = samples.get(path, path)
            matched = _first_handler(handlers[method], concrete)
            self.assertIsNotNone(matched, f"{method} {documented}")
            if "<" in path:
                self.assertEqual(matched[1], path.split("<", 1)[0])
            else:
                self.assertEqual(matched, ("exact", path))
            if path == "/api/import":
                documented_modes = {
                    parse_qs(query).get("mode", ["append"])[0],
                    *(_extra_mode_tokens(documented)),
                }
                self.assertEqual(documented_modes, _accepted_import_modes())

    def test_documented_cleanup_flags_match_argparse(self):
        options = _cleanup_options(ROOT / "app" / "cleanup.py")
        section = _section(self.guide, "### Remove unreferenced images", "## ")
        command_flags = set()
        for block in _fenced_blocks(section, "sh"):
            for line in block.splitlines():
                if "app.cleanup" not in line:
                    continue
                command_flags.update(
                    token for token in shlex.split(line) if token.startswith("--")
                )
        prose_flags = {
            token.strip("`").rstrip(".,")
            for token in section.split()
            if token.strip("`").startswith("--")
        }
        self.assertEqual(command_flags, prose_flags)
        self.assertTrue(command_flags)
        self.assertLessEqual(command_flags, set(options))
        self.assertEqual(options["--delete"], "store_true")


def _angle_placeholders(token):
    found = []
    start = None
    for index, character in enumerate(token):
        if character == "<":
            start = index
        elif character == ">" and start is not None:
            found.append(token[start:index + 1])
            start = None
    return found


def _fenced_blocks(text, language):
    blocks = []
    lines = text.splitlines()
    index = 0
    opener = "```" + language
    while index < len(lines):
        if lines[index].strip() == opener:
            index += 1
            body = []
            while index < len(lines) and lines[index].strip() != "```":
                body.append(lines[index])
                index += 1
            blocks.append("\n".join(body))
        index += 1
    return blocks


def _section(text, start_heading, next_prefix):
    start = text.index(start_heading)
    rest = text[start + len(start_heading):]
    for line in rest.splitlines(keepends=True):
        if line.startswith(next_prefix):
            return text[start:start + len(start_heading) + rest.index(line)]
    return text[start:]


def _parse_compose(path):
    items = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        items.append((len(raw) - len(raw.lstrip(" ")), raw.strip()))
    value, index = _parse_block(items, 0, 0)
    if index != len(items):
        raise AssertionError(f"unparsed compose lines at {items[index]}")
    return value


def _parse_block(items, index, indent):
    node = None
    while index < len(items):
        current, text = items[index]
        if current < indent:
            break
        if current != indent:
            raise AssertionError(f"unexpected indent in {text!r}")
        if text.startswith("- "):
            if node is None:
                node = []
            if not isinstance(node, list):
                raise AssertionError(f"mixed list and mapping at {text!r}")
            node.append(_scalar(text[2:]))
            index += 1
            continue
        if node is None:
            node = {}
        if not isinstance(node, dict):
            raise AssertionError(f"mixed mapping and list at {text!r}")
        key, separator, rest = text.partition(":")
        if not separator:
            raise AssertionError(f"expected key in {text!r}")
        rest = rest.strip()
        index += 1
        if not rest:
            child, index = _parse_block(items, index, current + 2)
            node[key] = {} if child is None else child
        elif rest.startswith("!"):
            tag, _, flow = rest.partition(" ")
            node[key] = {"tag": tag, "value": _flow(flow)}
        else:
            node[key] = _scalar(rest)
    return node, index


def _scalar(text):
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


def _flow(text):
    if text == "[]":
        return []
    raise AssertionError(f"unsupported flow value {text!r}")


def _host_port(mapping):
    published, separator, _container = mapping.partition(":")
    if not separator:
        raise AssertionError(f"port mapping has no host port: {mapping}")
    return published


def _operator_endpoints(guide):
    start = guide.index("| Method | Path | Result |")
    rows = []
    for line in guide[start:].splitlines()[2:]:
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        rows.append((cells[0], cells[1]))
    if not rows:
        raise AssertionError("operator endpoint table is empty")
    return rows


def _documented_request(cell):
    spans = [part for index, part in enumerate(cell.split("`")) if index % 2 == 1]
    if not spans:
        raise AssertionError(f"endpoint cell has no path: {cell}")
    parsed = urlparse(spans[0])
    return parsed.path, parsed.query


def _extra_mode_tokens(cell):
    spans = [part for index, part in enumerate(cell.split("`")) if index % 2 == 1]
    modes = []
    for span in spans[1:]:
        name, separator, value = span.partition("=")
        if separator and name == "mode":
            modes.append(value)
    return modes


def _server_handlers(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    constants = _module_strings(
        ROOT / "app" / "images.py",
        ROOT / "app" / "thumbs.py",
    )
    handlers = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in {"do_GET", "do_POST"}:
            continue
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name in {"do_GET", "do_POST"}:
                method = item.name.removeprefix("do_")
                handlers[method] = _path_checks(item, constants)
    return handlers


def _module_strings(*paths):
    values = {}
    for path in paths:
        module = path.stem
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assigned = {}
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            assigned[target.id] = _eval_constant(node.value, assigned, values)
        for name, value in assigned.items():
            if isinstance(value, str):
                values[(module, name)] = value
    return values


def _eval_constant(node, local, imported):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _eval_constant(node.left, local, imported)
        right = _eval_constant(node.right, local, imported)
        if isinstance(left, str) and isinstance(right, str):
            return left + right
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return imported.get((node.value.id, node.attr))
    if isinstance(node, ast.Name):
        return local.get(node.id)
    return None


def _path_checks(function, constants):
    checks = []

    def visit(node):
        if isinstance(node, ast.If):
            check = _path_check(node.test, constants)
            if check:
                checks.append(check)
            for child in node.body:
                visit(child)
            for child in node.orelse:
                visit(child)
        elif isinstance(node, (ast.Try, ast.With)):
            for child in ast.iter_child_nodes(node):
                visit(child)
        elif isinstance(node, (list, tuple)):
            for child in node:
                visit(child)

    for statement in function.body:
        visit(statement)
    return checks


def _path_check(test, constants):
    if (
        isinstance(test, ast.Compare)
        and len(test.ops) == 1
        and isinstance(test.ops[0], ast.Eq)
        and _attribute_chain(test.left) == ("url", "path")
    ):
        value = _eval_constant(test.comparators[0], {}, constants)
        if isinstance(value, str):
            return ("exact", value)
    if (
        isinstance(test, ast.Call)
        and isinstance(test.func, ast.Attribute)
        and test.func.attr == "startswith"
        and _attribute_chain(test.func.value) == ("url", "path")
        and len(test.args) == 1
    ):
        value = _eval_constant(test.args[0], {}, constants)
        if isinstance(value, str):
            return ("prefix", value)
    return None


def _attribute_chain(node):
    names = []
    while isinstance(node, ast.Attribute):
        names.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        names.append(node.id)
    return tuple(reversed(names))


def _first_handler(checks, path):
    for kind, value in checks:
        if kind == "exact" and path == value:
            return (kind, value)
        if kind == "prefix" and path.startswith(value):
            return (kind, value)
    return None


def _accepted_import_modes():
    tree = ast.parse((ROOT / "app" / "db.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        for operator, comparator in zip(node.ops, node.comparators):
            if not isinstance(operator, ast.NotIn) or not isinstance(comparator, ast.Tuple):
                continue
            values = [
                element.value for element in comparator.elts
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            ]
            if "append" in values and "replace" in values:
                return set(values)
    raise AssertionError("import modes are not declared in app/db.py")


def _cleanup_options(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    options = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "add_argument":
            continue
        action = None
        for keyword in node.keywords:
            if keyword.arg == "action" and isinstance(keyword.value, ast.Constant):
                action = keyword.value.value
        for argument in node.args:
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                if argument.value.startswith("--"):
                    options[argument.value] = action
    if not options:
        raise AssertionError("cleanup argparse options were not found")
    return options


if __name__ == "__main__":
    unittest.main()
