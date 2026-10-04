import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.server import main


class StartupTest(unittest.TestCase):
    def test_empty_storage_is_created_before_serving(self):
        for custom_images in (False, True):
            with self.subTest(custom_images=custom_images):
                with tempfile.TemporaryDirectory(dir=Path.cwd()) as root:
                    db_path = Path(root) / "nested" / "data" / "postcards.db"
                    image_dir = (Path(root) / "separate" / "images" if custom_images
                                 else db_path.parent / "images")
                    env = {"PPM_DB_PATH": str(db_path)}
                    if custom_images:
                        env["PPM_IMAGE_DIR"] = str(image_dir)
                    with patch.dict(os.environ, env, clear=True), \
                            patch("app.server.make_server") as make_server:
                        def check_storage(*args):
                            self.assertTrue(db_path.parent.is_dir())
                            self.assertTrue(image_dir.is_dir())
                            return make_server.return_value

                        make_server.side_effect = check_storage
                        main()
                        make_server.assert_called_once_with(
                            "127.0.0.1", 8000, str(db_path),
                            str(image_dir) if custom_images else image_dir,
                        )
                        make_server.return_value.serve_forever.assert_called_once()
                        make_server.return_value.server_close.assert_called_once()

    def test_invalid_storage_fails_before_serving(self):
        for blocked_directory in ("database", "images"):
            with self.subTest(blocked_directory=blocked_directory):
                with tempfile.TemporaryDirectory(dir=Path.cwd()) as root:
                    db_dir = Path(root) / "data"
                    image_dir = Path(root) / "images"
                    blocked = db_dir if blocked_directory == "database" else image_dir
                    blocked.write_text("not a directory")
                    env = {
                        "PPM_DB_PATH": str(db_dir / "postcards.db"),
                        "PPM_IMAGE_DIR": str(image_dir),
                    }
                    with patch.dict(os.environ, env, clear=True), \
                            patch("app.server.make_server") as make_server:
                        with self.assertRaises(OSError):
                            main()
                        make_server.assert_not_called()
