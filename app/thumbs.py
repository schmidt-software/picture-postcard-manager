"""Optional server-side thumbnails for the overview previews.

Thumbnails need the optional Pillow library; the standard library cannot
decode or resize JPEG, WebP or GIF. When Pillow is not installed the app keeps
working unchanged: thumbnail requests transparently serve the original image
(see server.py), nothing is generated and no error is raised.

Thumbnails are generated lazily on the first request for an image (which also
covers images uploaded before this feature existed) and cached on disk in a
``thumbs/`` directory inside the image directory. Cache files are written to a
temporary file first and moved into place atomically, so concurrent requests
never serve a partial file. The cache can always be regenerated from the
originals, so it is optional in backups and is covered by the orphaned-image
cleanup command.
"""

import io
import os
import re
import tempfile

from app import images

try:
    from PIL import Image, ImageOps
except ImportError:  # Pillow is optional; thumbnails are simply disabled.
    Image = ImageOps = None

PIL_AVAILABLE = Image is not None

# Longest side of a generated thumbnail in pixels.
THUMB_SIZE = 400
# Decompression-bomb protection: sources with more pixels are not thumbnailed
# (the original is served instead). Checked from the header before decoding.
MAX_SOURCE_PIXELS = 64_000_000
URL_PREFIX = images.URL_PREFIX + "thumbs/"
DIR_NAME = "thumbs"
JPEG_QUALITY = 80

# Cached thumbnail names derive from the original's generated name plus the
# size and output format: <32 hex>.<size>.<jpg|png>. Transparent sources keep
# their transparency as PNG; everything else becomes JPEG.
THUMB_PATTERN = re.compile(rf"^[0-9a-f]{{32}}\.{THUMB_SIZE}\.(?:jpg|png)$")
OUTPUT_EXTENSIONS = ("jpg", "png")

if PIL_AVAILABLE:
    # Explicit limit instead of Pillow's default; DecompressionBombError from
    # Image.open is treated like any other undecodable image below.
    Image.MAX_IMAGE_PIXELS = MAX_SOURCE_PIXELS


class ThumbnailStore:
    """Lazily generated, disk-cached thumbnails for an ImageStore."""

    def __init__(self, store):
        self.store = store
        self.root = store.root / DIR_NAME

    def thumb_name(self, name, extension):
        return f"{name.rsplit('.', 1)[0]}.{THUMB_SIZE}.{extension}"

    def open(self, name):
        """Return (content_type, size, file) for the thumbnail of original
        `name`, generating and caching it on first use, or None when no
        thumbnail can be provided (Pillow missing, unknown name, undecodable
        or oversized source). The caller must close the returned file and is
        expected to fall back to the original image on None.
        """
        if not images.NAME_PATTERN.fullmatch(name):
            return None
        for extension in OUTPUT_EXTENSIONS:
            cached = images.open_stored(self.root, self.thumb_name(name, extension),
                                        THUMB_PATTERN)
            if cached is not None:
                return cached
        if not PIL_AVAILABLE:
            return None
        generated = self._generate(name)
        if generated is None:
            return None
        return images.open_stored(self.root, generated, THUMB_PATTERN)

    def _render(self, file):
        """Return (bytes, extension) for the thumbnail of an open source file.

        EXIF orientation is applied, animated GIFs use their first frame, and
        transparency is preserved as PNG; opaque images become JPEG.
        """
        with Image.open(file) as source:
            # Reject decompression bombs from the header, before decoding.
            if source.width * source.height > MAX_SOURCE_PIXELS:
                return None
            transposed = ImageOps.exif_transpose(source)
            has_alpha = (transposed.mode in ("RGBA", "LA", "PA")
                         or "transparency" in transposed.info)
            # convert() decodes the first frame of animated sources.
            image = transposed.convert("RGBA" if has_alpha else "RGB")
        image.thumbnail((THUMB_SIZE, THUMB_SIZE))
        buffer = io.BytesIO()
        if has_alpha:
            image.save(buffer, "PNG", optimize=True)
            return buffer.getvalue(), "png"
        image.save(buffer, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
        return buffer.getvalue(), "jpg"

    def _generate(self, name):
        """Create and cache the thumbnail for original `name`.

        Returns the cached thumbnail's file name, or None when the original is
        missing, undecodable, oversized or the cache cannot be written. A
        corrupt source never raises: the caller falls back to the original.
        """
        opened = self.store.open(name)
        if opened is None:
            return None
        _, _, file = opened
        try:
            with file:
                rendered = self._render(file)
        except Exception:  # noqa: BLE001 - corrupt input must not crash the request.
            return None
        if rendered is None:
            return None
        data, extension = rendered
        thumb = self.thumb_name(name, extension)
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.root, suffix=".tmp")
        except OSError:
            return None
        try:
            with os.fdopen(fd, "wb") as out:
                out.write(data)
                out.flush()
                os.fsync(out.fileno())
            os.replace(tmp, self.root / thumb)  # Atomic: readers never see a partial file.
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            return None
        # Drop a stale cache entry in the other output format, if any.
        other = self.thumb_name(name, "png" if extension == "jpg" else "jpg")
        (self.root / other).unlink(missing_ok=True)
        return thumb
