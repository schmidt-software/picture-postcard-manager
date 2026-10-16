import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from app.server import make_server


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = make_server("127.0.0.1", 0, str(Path(self.tmp.name) / "test.db"))
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.server.RequestHandlerClass.db.close()
        self.tmp.cleanup()

    def request(self, method, path, data=None, raw=None):
        body = raw if raw is not None else (json.dumps(data).encode() if data is not None else None)
        req = urllib.request.Request(self.base + path, data=body, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as res:
                content = res.read()
                return res.status, json.loads(content) if content else None
        except urllib.error.HTTPError as err:
            with err:
                return err.code, json.loads(err.read())

    def test_crud(self):
        data = {
            "front_image_path": "images/berlin-front.jpg",
            "back_image_path": "images/berlin-back.jpg",
            "year": "1910", "description": "Street view",
            "tags": ["Berlin", "Brandenburg"],
        }
        status, created = self.request("POST", "/api/postcards", data)
        self.assertEqual(status, 201)
        for key, value in data.items():
            self.assertEqual(created[key], value)
        for obsolete in ("title", "notes", "place", "region"):
            self.assertNotIn(obsolete, created)
        pid = created["id"]

        status, items = self.request("GET", "/api/postcards")
        self.assertEqual([p["tags"] for p in items], [["Berlin", "Brandenburg"]])

        status, updated = self.request("PUT", f"/api/postcards/{pid}", {"tags": ["Munich"]})
        self.assertEqual(status, 200)
        self.assertEqual(updated["tags"], ["Munich"])
        for key, value in data.items():
            if key != "tags":
                self.assertEqual(updated[key], value)
        self.assertEqual(updated["created_at"], created["created_at"])

        status, fetched = self.request("GET", f"/api/postcards/{pid}")
        self.assertEqual((status, fetched), (200, updated))

        status, found = self.request("GET", "/api/postcards?q=Mun")
        self.assertEqual(len(found), 1)
        status, found = self.request("GET", "/api/postcards?q=Street")
        self.assertEqual(len(found), 1)

        status, _ = self.request("DELETE", f"/api/postcards/{pid}")
        self.assertEqual(status, 204)
        status, _ = self.request("GET", f"/api/postcards/{pid}")
        self.assertEqual(status, 404)

    def test_obsolete_location_fields_are_rejected(self):
        """The current API rejects place/region instead of silently dropping them."""
        for field in ("place", "region"):
            with self.subTest(field=field):
                status, body = self.request(
                    "POST", "/api/postcards",
                    {"front_image_path": "/f.jpg", field: "Wien"})
                self.assertEqual(status, 400)
                self.assertIn(field, body["error"])
        _, created = self.request("POST", "/api/postcards", {"front_image_path": "/f.jpg"})
        status, body = self.request(
            "PUT", f"/api/postcards/{created['id']}", {"region": "Tirol"})
        self.assertEqual(status, 400)
        self.assertIn("region", body["error"])
        self.assertEqual(self.request("GET", f"/api/postcards/{created['id']}")[1], created)
        # Obsolete sort and filter parameters return the validation error.
        for query in ("sort=place", "sort=region", "place=Wien", "region=Tirol"):
            with self.subTest(query=query):
                status, body = self.request("GET", f"/api/postcards?{query}")
                self.assertEqual(status, 400)
                self.assertIn("error", body)

    def test_export_import_roundtrip(self):
        data = {
            "front_image_path": "/front.jpg",
            "back_image_path": "/back.jpg", "year": "1900",
            "description": "A historic view", "tags": ["Berlin"],
        }
        self.request("POST", "/api/postcards", data)
        self.request("POST", "/api/postcards", {"front_image_path": "/b.jpg"})
        _, export = self.request("GET", "/api/export")
        self.assertEqual(export["format"], "picture-postcard-manager")
        self.assertEqual(export["schema_version"], 6)
        self.assertEqual(len(export["postcards"]), 2)
        for postcard in export["postcards"]:
            for obsolete in ("title", "notes", "place", "region"):
                self.assertNotIn(obsolete, postcard)

        status, result = self.request("POST", "/api/import?mode=append", export)
        self.assertEqual((status, result["imported"]), (200, 2))
        _, items = self.request("GET", "/api/postcards")
        self.assertEqual(len(items), 4)
        originals = [{k: v for k, v in item.items() if k not in ("id", "uuid")}
                     for item in export["postcards"]]
        copies = [{k: v for k, v in item.items() if k not in ("id", "uuid")} for item in items]
        for original in originals:
            self.assertEqual(copies.count(original), 2)

        status, _ = self.request("POST", "/api/import?mode=replace", export)
        self.assertEqual(status, 200)
        _, items = self.request("GET", "/api/postcards")
        self.assertEqual(items, export["postcards"])

    def test_required_front_image_path(self):
        for value in (None, "", " \t\n", 123, False, [], {}):
            with self.subTest(value=value):
                status, body = self.request("POST", "/api/postcards", {"front_image_path": value})
                self.assertEqual(status, 400)
                self.assertIn("front_image_path", body["error"])
        status, body = self.request("POST", "/api/postcards", {"description": "Berlin"})
        self.assertEqual(status, 400)
        self.assertIn("front_image_path", body["error"])
        _, items = self.request("GET", "/api/postcards")
        self.assertEqual(items, [])

    def test_optional_fields_and_partial_update(self):
        optional = ("back_image_path", "year", "description")
        status, empty = self.request("POST", "/api/postcards", {
            "front_image_path": "/nullable.jpg", **dict.fromkeys(optional),
        })
        self.assertEqual(status, 201)
        for field in optional:
            self.assertEqual(empty[field], "")
        status, created = self.request("POST", "/api/postcards", {"front_image_path": "/front.jpg"})
        self.assertEqual(status, 201)
        for field in optional:
            self.assertEqual(created[field], "")
        path = f"/api/postcards/{created['id']}"
        status, updated = self.request("PUT", path, {
            "back_image_path": "/back.jpg", "year": 1910, "description": "View",
        })
        self.assertEqual(status, 200)
        self.assertEqual(updated["year"], "1910")
        self.assertEqual(updated["front_image_path"], "/front.jpg")
        status, unchanged = self.request("PUT", path, {})
        self.assertEqual(status, 200)
        for field in ("front_image_path", *optional):
            self.assertEqual(unchanged[field], updated[field])
        status, cleared = self.request("PUT", path, {
            "back_image_path": None, "year": None, "description": None,
        })
        self.assertEqual(status, 200)
        for field in optional:
            self.assertEqual(cleared[field], "")
        status, changed = self.request("PUT", path, {"front_image_path": "/new.jpg"})
        self.assertEqual((status, changed["front_image_path"]), (200, "/new.jpg"))

    def test_invalid_updates_do_not_modify_record(self):
        _, created = self.request("POST", "/api/postcards", {"front_image_path": "/front.jpg"})
        path = f"/api/postcards/{created['id']}"
        for value in (None, "", " \n", 123, False, [], {}):
            with self.subTest(value=value):
                status, body = self.request("PUT", path, {"front_image_path": value, "year": "1910"})
                self.assertEqual(status, 400)
                self.assertIn("front_image_path", body["error"])
                self.assertEqual(self.request("GET", path)[1], created)
        for field in ("back_image_path", "year", "description", "place", "region", "unknown"):
            with self.subTest(field=field):
                status, body = self.request("PUT", path, {field: []})
                self.assertEqual(status, 400)
                self.assertIn(field, body["error"])
                self.assertEqual(self.request("GET", path)[1], created)
        self.assertEqual(self.request("PUT", "/api/postcards/999", {"year": "1910"})[0], 404)

    def test_invalid_field_types_and_unknown_data(self):
        for data in (
            [], None, {"unexpected": "keep me"}, {"back_image_path": []},
            {"year": False}, {"description": 123},
        ):
            with self.subTest(data=data):
                payload = dict(data, front_image_path="/front.jpg") if isinstance(data, dict) else data
                status, body = self.request("POST", "/api/postcards", payload, raw=b"null" if data is None else None)
                self.assertEqual(status, 400)
                self.assertIn("error", body)

    def test_import_errors_are_atomic_and_actionable(self):
        _, created = self.request("POST", "/api/postcards", {"front_image_path": "/existing.jpg"})
        for payload in (
            {"postcards": [{"front_image_path": "/valid.jpg"}, {"year": "Missing front"}]},
            {"postcards": [{"front_image_path": ""}]},
            {"postcards": [{"front_image_path": "/front.jpg", "unknown": "data"}]},
            {"postcards": [], "unknown": "data"},
            {"schema_version": 99, "postcards": []},
            {"postcards": [{"front_image_path": "/front.jpg", "id": "bad"}]},
            {"postcards": [{"front_image_path": "/front.jpg", "id": 2**63}]},
            {"postcards": [{"front_image_path": "/front.jpg", "created_at": []}]},
            {"postcards": [{"front_image_path": "/one.jpg", "id": 1},
                           {"front_image_path": "/two.jpg", "id": 1}]},
        ):
            with self.subTest(payload=payload):
                status, body = self.request("POST", "/api/import?mode=replace", payload)
                self.assertEqual(status, 400)
                self.assertIn("error", body)
                self.assertEqual(self.request("GET", "/api/postcards")[1], [created])

    def test_legacy_import_and_edit(self):
        payload = {
            "format": "picture-postcard-manager", "schema_version": 1,
            "postcards": [{"id": 7, "title": "Legacy", "notes": "Keep me",
                          "created_at": "old-created", "updated_at": "old-updated"}],
        }
        status, _ = self.request("POST", "/api/import?mode=replace", payload)
        self.assertEqual(status, 200)
        _, legacy = self.request("GET", "/api/postcards/7")
        self.assertEqual(legacy["description"], "Legacy\n\nKeep me")
        self.assertNotIn("title", legacy)
        self.assertNotIn("notes", legacy)
        self.assertEqual(legacy["front_image_path"], "")
        status, body = self.request("PUT", "/api/postcards/7", {"year": "1900"})
        self.assertEqual(status, 400)
        self.assertIn("front_image_path", body["error"])
        _, export = self.request("GET", "/api/export")
        self.assertEqual(self.request("POST", "/api/import?mode=replace", export)[0], 200)
        self.assertEqual(self.request("GET", "/api/postcards/7")[1], legacy)
        status, repaired = self.request("PUT", "/api/postcards/7", {"front_image_path": "/legacy.jpg"})
        self.assertEqual(status, 200)
        self.assertEqual(repaired["description"], "Legacy\n\nKeep me")

    def test_v4_import_merges_legacy_fields(self):
        """Version-4 exports with title/notes/place/region import into description/tags."""
        payload = {
            "format": "picture-postcard-manager", "schema_version": 4,
            "postcards": [
                {"id": 1, "uuid": "b962a358-8899-4000-8999-6973bac5d591",
                 "title": "Berlin", "notes": "From grandma",
                 "front_image_path": "/front.jpg", "back_image_path": "",
                 "place": "Berlin", "region": "", "year": "1910",
                 "description": "Street view", "tags": ["old"],
                 "created_at": "c", "updated_at": "u"},
                {"id": 2, "uuid": "b962a358-8899-4000-8999-6973bac5d592",
                 "title": "", "notes": "", "front_image_path": "/plain.jpg",
                 "back_image_path": "", "place": "", "region": "", "year": "",
                 "description": "Only description", "tags": [],
                 "created_at": "c", "updated_at": "u"},
            ],
        }
        status, result = self.request("POST", "/api/import?mode=replace", payload)
        self.assertEqual((status, result["imported"]), (200, 2))
        _, merged = self.request("GET", "/api/postcards/1")
        self.assertEqual(merged["description"], "Berlin\n\nFrom grandma\n\nStreet view")
        self.assertEqual(merged["tags"], ["old", "Berlin"])
        for obsolete in ("title", "notes", "place", "region"):
            self.assertNotIn(obsolete, merged)
        _, plain = self.request("GET", "/api/postcards/2")
        self.assertEqual(plain["description"], "Only description")
        self.assertEqual(plain["tags"], [])

    def test_v5_import_converts_location_fields_to_tags(self):
        """Version-5 exports with place/region import their values as tags."""
        payload = {
            "format": "picture-postcard-manager", "schema_version": 5,
            "postcards": [
                {"id": 1, "uuid": "b962a358-8899-4000-8999-6973bac5d591",
                 "front_image_path": "/front.jpg", "back_image_path": "",
                 "place": "Wien", "region": "Wien", "year": "1910",
                 "description": "", "tags": ["Stadt"],
                 "created_at": "c", "updated_at": "u"},
                {"id": 2, "uuid": "b962a358-8899-4000-8999-6973bac5d592",
                 "front_image_path": "/f.jpg", "back_image_path": "",
                 "place": "  ", "region": " Großglockner ✉ ", "year": "",
                 "description": "", "tags": [],
                 "created_at": "c", "updated_at": "u"},
            ],
        }
        status, result = self.request("POST", "/api/import?mode=replace", payload)
        self.assertEqual((status, result["imported"]), (200, 2))
        _, first = self.request("GET", "/api/postcards/1")
        # Equal place and region produce one tag; existing tags come first.
        self.assertEqual(first["tags"], ["Stadt", "Wien"])
        self.assertNotIn("place", first)
        self.assertNotIn("region", first)
        _, second = self.request("GET", "/api/postcards/2")
        # Blank values are skipped; non-blank ones are trimmed like tags.
        self.assertEqual(second["tags"], ["Großglockner ✉"])
        # Migrated values are found through search and tag filter.
        _, found = self.request("GET", "/api/postcards?q=Wien")
        self.assertEqual([p["id"] for p in found], [1])
        _, found = self.request("GET", "/api/postcards?tag=Wien")
        self.assertEqual([p["id"] for p in found], [1])

    def test_old_imports_convert_location_fields_in_every_version(self):
        """Every supported older schema version imports place/region as tags."""
        for version in (1, 2, 3, 4, 5):
            with self.subTest(version=version):
                entry = {"front_image_path": "/f.jpg", "place": "Graz",
                         "region": "Steiermark", "tags": ["Gruß aus"]}
                if version >= 4:
                    entry["uuid"] = "b962a358-8899-4000-8999-6973bac5d591"
                    entry["id"] = 1
                status, result = self.request(
                    "POST", "/api/import?mode=replace",
                    {"schema_version": version, "postcards": [entry]})
                self.assertEqual((status, result["imported"]), (200, 1))
                _, items = self.request("GET", "/api/postcards")
                self.assertEqual(items[0]["tags"], ["Gruß aus", "Graz", "Steiermark"])

    def test_bare_import_without_schema_version_rejects_location_fields(self):
        """Payloads without schema_version are treated as the current version.

        They never carried place/region support guarantees for old clients,
        so obsolete fields are rejected rather than silently dropped or
        silently reinterpreted.
        """
        _, created = self.request("POST", "/api/postcards", {"front_image_path": "/keep.jpg"})
        status, body = self.request("POST", "/api/import?mode=append", {
            "postcards": [{"front_image_path": "/f.jpg", "place": "Wien"}],
        })
        self.assertEqual(status, 400)
        self.assertIn("place", body["error"])
        # Bare imports without obsolete fields keep working unchanged.
        status, result = self.request("POST", "/api/import?mode=append", {
            "postcards": [{"front_image_path": "/f.jpg", "tags": ["Wien"]}],
        })
        self.assertEqual((status, result["imported"]), (200, 1))
        self.assertEqual(self.request("GET", "/api/postcards")[1][0]["tags"], ["Wien"])

    def test_v6_import_rejects_legacy_fields(self):
        _, created = self.request("POST", "/api/postcards", {"front_image_path": "/keep.jpg"})
        _, export = self.request("GET", "/api/export")
        for field in ("title", "place", "region"):
            with self.subTest(field=field):
                payload = dict(export, postcards=[dict(export["postcards"][0], **{field: "No more"})])
                status, body = self.request("POST", "/api/import?mode=replace", payload)
                self.assertEqual(status, 400)
                self.assertIn(field, body["error"])
                self.assertEqual(self.request("GET", "/api/postcards")[1], [created])

    def test_append_import_rolls_back_on_error(self):
        _, created = self.request("POST", "/api/postcards", {"front_image_path": "/existing.jpg"})
        status, body = self.request("POST", "/api/import", {
            "postcards": [{"front_image_path": "/valid.jpg"}, {"description": "Missing image"}],
        })
        self.assertEqual(status, 400)
        self.assertIn("postcard 2", body["error"])
        self.assertIn("front_image_path", body["error"])
        self.assertEqual(self.request("GET", "/api/postcards")[1], [created])

    def test_invalid_json_encoding_is_rejected(self):
        status, body = self.request("POST", "/api/postcards", raw=b'{"front_image_path": "\xff"}')
        self.assertEqual(status, 400)
        self.assertIn("invalid JSON", body["error"])

    def test_invalid_import_is_rejected(self):
        status, body = self.request("POST", "/api/import", {"foo": 1})
        self.assertEqual(status, 400)
        status, _ = self.request("POST", "/api/import", raw=b"not json")
        self.assertEqual(status, 400)

    def test_static_files(self):
        with urllib.request.urlopen(self.base + "/") as res:
            self.assertIn(b"Picture Postcard Manager", res.read())
        status, _ = self.request("GET", "/../server.py")
        self.assertEqual(status, 404)

    def test_es_modules_are_served_as_javascript(self):
        static = Path(__file__).resolve().parents[1] / "app" / "static"
        for path in ["/app.js", *(f"/js/{f.name}" for f in (static / "js").glob("*.js"))]:
            with urllib.request.urlopen(self.base + path) as res:
                self.assertEqual(res.status, 200, path)
                self.assertEqual(res.headers.get_content_type(), "text/javascript", path)
        for path in ("/js/../db.py", "/js/../../README.md", "/js/missing.js"):
            status, _ = self.request("GET", path)
            self.assertEqual(status, 404, path)


if __name__ == "__main__":
    unittest.main()
