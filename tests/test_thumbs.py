"""Tests for the optional server-side thumbnail cache (issue #28)."""

import io
import os
import unittest
from pathlib import Path
from unittest import mock

from app import thumbs
from app.thumbs import ThumbnailStore
from tests.test_images import PNG, ImageApiTest

try:
    from PIL import Image
except ImportError:
    Image = None


def make_image(mode, size, format, **save_args):
    """Return encoded bytes of a generated Pillow test image."""
    image = Image.new(mode, size, (200, 120, 40) if mode == "RGB" else (0, 200, 0, 128))
    buffer = io.BytesIO()
    image.save(buffer, format, **save_args)
    return buffer.getvalue()


class ThumbApiTest(ImageApiTest):
    """HTTP-level base: upload originals and request their thumbnails."""

    @property
    def thumb_dir(self):
        return self.server.RequestHandlerClass.thumbs.root

    def upload_name(self, data, ctype="image/png"):
        status, result = self.upload(data, ctype)
        self.assertEqual(status, 201)
        return result["path"].rsplit("/", 1)[1]

    def get_thumb(self, name):
        return self.raw("GET", thumbs.URL_PREFIX + name)


class FallbackTest(ThumbApiTest):
    """Without Pillow the thumbnail URL transparently serves the original."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(thumbs, "PIL_AVAILABLE", False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_thumbnail_url_serves_original_without_pillow(self):
        name = self.upload_name(PNG)
        status, headers, body = self.get_thumb(name)
        self.assertEqual(status, 200)
        self.assertEqual(body, PNG)
        self.assertEqual(headers["Content-Type"], "image/png")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("sandbox", headers["Content-Security-Policy"])
        self.assertFalse(self.thumb_dir.exists())

    def test_unknown_thumbnail_is_not_found(self):
        status, headers, body = self.get_thumb("0" * 32 + ".png")
        self.assertEqual(status, 404)
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")

    def test_existing_cache_is_served_without_pillow(self):
        # A cache written earlier (e.g. by a Pillow-enabled deployment) keeps
        # working after Pillow is removed.
        name = self.upload_name(PNG)
        cached = name.rsplit(".", 1)[0] + f".{thumbs.THUMB_SIZE}.png"
        self.thumb_dir.mkdir()
        (self.thumb_dir / cached).write_bytes(PNG)
        status, _, body = self.get_thumb(name)
        self.assertEqual(status, 200)
        self.assertEqual(body, PNG)


class HardeningTest(ThumbApiTest):
    def test_only_generated_names_reach_the_thumbnail_store(self):
        name = self.upload_name(PNG)
        for path in (
            thumbs.URL_PREFIX, thumbs.URL_PREFIX + "../" + name,
            thumbs.URL_PREFIX + "..%2f" + name, thumbs.URL_PREFIX + name.upper(),
            thumbs.URL_PREFIX + name + "/", thumbs.URL_PREFIX + "sub/" + name,
            thumbs.URL_PREFIX + "0" * 32 + ".svg",
            thumbs.URL_PREFIX + "0" * 32 + f".{thumbs.THUMB_SIZE}.jpg",
            "/images/thumbs", "/images/thumbsx/" + name,
        ):
            with self.subTest(path):
                self.assertEqual(self.raw("GET", path)[0], 404)

    def test_symlinked_or_mistyped_cache_entries_are_not_served(self):
        name = self.upload_name(PNG)
        stem = name.rsplit(".", 1)[0]
        self.thumb_dir.mkdir()
        outside = self.db_path.parent / "outside.png"
        outside.write_bytes(PNG)
        # Symlink and signature-mismatch cache entries must not be served;
        # the request falls back to the original instead.
        os.symlink(outside, self.thumb_dir / f"{stem}.{thumbs.THUMB_SIZE}.jpg")
        (self.thumb_dir / f"{stem}.{thumbs.THUMB_SIZE}.png").write_bytes(b"<script>")
        with mock.patch.object(thumbs, "PIL_AVAILABLE", False):
            status, headers, body = self.get_thumb(name)
        self.assertEqual(status, 200)
        self.assertEqual(body, PNG)
        self.assertEqual(headers["Content-Type"], "image/png")


@unittest.skipUnless(Image, "Pillow is optional; generation tests need it")
class GenerationTest(ThumbApiTest):
    def cached_files(self):
        return sorted(f.name for f in self.thumb_dir.iterdir()) if self.thumb_dir.exists() else []

    def assertThumb(self, body, headers, format, max_side=thumbs.THUMB_SIZE):
        with Image.open(io.BytesIO(body)) as thumb:
            self.assertEqual(thumb.format, format)
            self.assertLessEqual(max(thumb.size), max_side)
            return thumb.size

    def test_jpeg_thumbnail_is_resized_cached_and_reused(self):
        name = self.upload_name(make_image("RGB", (1600, 1200), "JPEG"), "image/jpeg")
        status, headers, body = self.get_thumb(name)
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "image/jpeg")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("sandbox", headers["Content-Security-Policy"])
        self.assertEqual(self.assertThumb(body, headers, "JPEG"), (400, 300))
        cached = name.rsplit(".", 1)[0] + f".{thumbs.THUMB_SIZE}.jpg"
        self.assertEqual(self.cached_files(), [cached])
        self.assertTrue(thumbs.THUMB_PATTERN.fullmatch(cached))
        # The cache is reused: a second request serves identical bytes even
        # after the original vanishes.
        (self.store_dir / name).unlink()
        self.assertEqual(self.get_thumb(name)[2], body)

    def test_exif_orientation_is_applied(self):
        exif = Image.Exif()
        exif[274] = 6  # Rotate 90° CW on display.
        name = self.upload_name(make_image("RGB", (800, 400), "JPEG", exif=exif),
                                "image/jpeg")
        _, headers, body = self.get_thumb(name)
        self.assertEqual(self.assertThumb(body, headers, "JPEG"), (200, 400))

    def test_transparency_is_preserved_as_png(self):
        name = self.upload_name(make_image("RGBA", (800, 600), "PNG"))
        status, headers, body = self.get_thumb(name)
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "image/png")
        self.assertThumb(body, headers, "PNG")
        with Image.open(io.BytesIO(body)) as thumb:
            self.assertEqual(thumb.mode, "RGBA")
            self.assertEqual(thumb.getpixel((0, 0))[3], 128)

    def test_animated_gif_uses_first_frame(self):
        first = Image.new("RGB", (600, 600), (255, 0, 0))
        second = Image.new("RGB", (600, 600), (0, 0, 255))
        buffer = io.BytesIO()
        first.save(buffer, "GIF", save_all=True, append_images=[second], duration=100)
        name = self.upload_name(buffer.getvalue(), "image/gif")
        status, headers, body = self.get_thumb(name)
        self.assertEqual(status, 200)
        with Image.open(io.BytesIO(body)) as thumb:
            self.assertEqual(getattr(thumb, "n_frames", 1), 1)
            red, green, blue = thumb.convert("RGB").getpixel((10, 10))
            self.assertGreater(red, 200)
            self.assertLess(blue, 60)

    def test_small_images_are_not_upscaled(self):
        name = self.upload_name(make_image("RGB", (120, 90), "JPEG"), "image/jpeg")
        _, headers, body = self.get_thumb(name)
        self.assertEqual(self.assertThumb(body, headers, "JPEG"), (120, 90))

    def test_corrupt_image_falls_back_to_original(self):
        # Valid signature, undecodable payload: the request must not crash and
        # serves the original; nothing is cached.
        name = self.upload_name(PNG)
        status, _, body = self.get_thumb(name)
        self.assertEqual(status, 200)
        self.assertEqual(body, PNG)
        self.assertEqual(self.cached_files(), [])

    def test_oversized_image_falls_back_to_original(self):
        data = make_image("RGB", (300, 300), "JPEG")
        name = self.upload_name(data, "image/jpeg")
        with mock.patch.object(thumbs, "MAX_SOURCE_PIXELS", 300 * 300 - 1):
            status, _, body = self.get_thumb(name)
        self.assertEqual(status, 200)
        self.assertEqual(body, data)
        self.assertEqual(self.cached_files(), [])

    def test_unwritable_cache_directory_still_serves(self):
        name = self.upload_name(make_image("RGB", (800, 600), "JPEG"), "image/jpeg")
        with mock.patch.object(Path, "mkdir", side_effect=OSError):
            status, _, body = self.get_thumb(name)
        self.assertEqual(status, 200)
        with Image.open(io.BytesIO(body)) as served:
            self.assertEqual(served.size, (800, 600))

    def test_stale_other_format_cache_entry_is_replaced(self):
        name = self.upload_name(make_image("RGB", (800, 600), "JPEG"), "image/jpeg")
        stem = name.rsplit(".", 1)[0]
        self.thumb_dir.mkdir()
        stale = self.thumb_dir / f"{stem}.{thumbs.THUMB_SIZE}.png"
        stale.write_bytes(b"not a png")  # Wrong signature: never served.
        _, headers, _ = self.get_thumb(name)
        self.assertEqual(headers["Content-Type"], "image/jpeg")
        self.assertFalse(stale.exists())


class StoreUnitTest(unittest.TestCase):
    def test_thumb_name_encodes_size_and_format(self):
        store = ThumbnailStore(mock.Mock(root=Path("/tmp/x")))
        self.assertEqual(store.thumb_name("a" * 32 + ".png", "jpg"),
                         "a" * 32 + f".{thumbs.THUMB_SIZE}.jpg")

    def test_open_rejects_invalid_names_without_touching_disk(self):
        store = ThumbnailStore(mock.Mock(root=Path("/nonexistent")))
        for name in ("", "../x.png", "A" * 32 + ".png", "a" * 32 + ".svg"):
            self.assertIsNone(store.open(name))
