"""Storage for uploaded postcard images.

Only raster formats with a recognized file signature are accepted. Stored files
receive generated names, so client-supplied filenames and paths are never used.
"""

import os
import re
import secrets
import stat
from pathlib import Path

MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20 MiB
URL_PREFIX = "/images/"

# Declared Content-Type -> stored file extension.
CONTENT_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
}
EXTENSION_TYPES = {ext: ctype for ctype, ext in CONTENT_TYPES.items()}
NAME_PATTERN = re.compile(r"^[0-9a-f]{32}\.(?:png|jpg|gif|webp)$")

ERROR_EMPTY = "image upload must not be empty"
ERROR_TOO_LARGE = "image is too large (maximum 20 MiB)"
ERROR_UNSUPPORTED_TYPE = "unsupported image type; use PNG, JPEG, GIF or WebP"
ERROR_INVALID_CONTENT = "image content is not a valid PNG, JPEG, GIF or WebP file"
ERROR_STORAGE = "image could not be stored"
ERROR_NOT_FOUND = "image not found"

_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_BINARY = getattr(os, "O_BINARY", 0)
_NONBLOCK = getattr(os, "O_NONBLOCK", 0)


class ImageError(ValueError):
    """Client error for an upload; status is the HTTP status code."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def detect_extension(data):
    """Return the extension for a supported raster signature, or None."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


class ImageStore:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def validate(self, data, content_type):
        """Return the extension for valid upload data or raise ImageError."""
        if not data:
            raise ImageError(400, ERROR_EMPTY)
        if len(data) > MAX_IMAGE_BYTES:
            raise ImageError(413, ERROR_TOO_LARGE)
        declared = CONTENT_TYPES.get(content_type)
        if declared is None:
            raise ImageError(415, ERROR_UNSUPPORTED_TYPE)
        if detect_extension(data) != declared:
            raise ImageError(415, ERROR_INVALID_CONTENT)
        return declared

    def save(self, data, content_type):
        """Store a validated image and return its URL path.

        Raises ImageError for invalid uploads and OSError for storage failures.
        """
        extension = self.validate(data, content_type)
        self.root.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _BINARY
        for _ in range(5):
            name = f"{secrets.token_hex(16)}.{extension}"
            path = self.root / name
            try:
                fd = os.open(path, flags, 0o644)
            except FileExistsError:
                continue
            try:
                with os.fdopen(fd, "wb") as file:
                    file.write(data)
                    file.flush()
                    os.fsync(file.fileno())
            except BaseException:
                path.unlink(missing_ok=True)
                raise
            return URL_PREFIX + name
        raise FileExistsError("could not generate a unique image name")

    def read(self, name):
        """Return (content_type, bytes) for a stored image, or None.

        Only generated names of regular, non-symlinked files directly inside the
        store whose content matches the extension are served.
        """
        if not NAME_PATTERN.fullmatch(name):
            return None
        path = self.root / name
        try:
            if path.is_symlink():
                return None
            fd = os.open(path, os.O_RDONLY | _NOFOLLOW | _NONBLOCK | _BINARY)
        except OSError:
            return None
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_IMAGE_BYTES:
                return None
            chunks = []
            remaining = MAX_IMAGE_BYTES + 1
            while remaining and (chunk := os.read(fd, min(remaining, 1024 * 1024))):
                chunks.append(chunk)
                remaining -= len(chunk)
            data = b"".join(chunks)
        except OSError:
            return None
        finally:
            os.close(fd)
        extension = name.rsplit(".", 1)[1]
        if len(data) > MAX_IMAGE_BYTES or detect_extension(data) != extension:
            return None
        return EXTENSION_TYPES[extension], data
