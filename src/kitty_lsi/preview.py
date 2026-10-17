"""Bounded local raster decoding. No network, subprocesses or persistent cache."""

import io
import os
from pathlib import Path
import stat
import warnings
from PIL import Image, ImageOps


IMAGE_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".ico", ".avif",
})
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_PIXELS = 40_000_000


def thumbnail(path: Path, columns: int, rows: int) -> tuple[bytes, tuple[int, int]]:
    """Decode only local raster files, cap resource use, preserve EXIF rotation."""
    # O_NONBLOCK prevents a swapped-in FIFO from hanging the command;
    # O_NOFOLLOW prevents following a swapped-in symlink during open.
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
            raise ValueError("not a regular file or larger than 64 MiB")
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(source) as image:
                if image.width * image.height > MAX_PIXELS:
                    raise ValueError("image exceeds 40 megapixels")
                # Shrink before transpose/conversion to avoid full-size copies.
                # Keep a square bound so portrait EXIF rotations also fit.
                bound = max(columns * 16, rows * 32)
                size = image.size
                orientation = image.getexif().get(274, 1)
                if orientation in (5, 6, 7, 8):
                    size = size[::-1]
                image.thumbnail((bound, bound), Image.Resampling.LANCZOS)
                preview = ImageOps.exif_transpose(image).convert("RGBA")
                output = io.BytesIO()
                preview.save(output, format="PNG")
                return output.getvalue(), size


