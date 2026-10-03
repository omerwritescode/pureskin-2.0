"""Decode the uploaded image entirely in memory. Nothing is written to disk."""

import base64
import binascii
import io
import re

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError

from . import scoring_config as cfg
from .errors import ImageRejected

UNREADABLE = "The image could not be read. Upload a JPEG or PNG photo."
TOO_LARGE = (
    f"The image is too large (over {cfg.MAX_IMAGE_PIXELS // 1_000_000} megapixels). "
    "Use a smaller photo."
)

_DATA_URL_PREFIX = re.compile(r"data:image/[\w.+-]+;base64,", re.ASCII)


def to_canonical_resolution(bgr: np.ndarray) -> np.ndarray:
    """Downscale so the longest side is at most CANONICAL_MAX_SIDE; never enlarge.

    Deterministic (cv2.INTER_AREA, exact target size), and a no-op on an image that is
    already small enough, so calling it twice changes nothing.
    """
    height, width = bgr.shape[:2]
    longest = max(height, width)
    if longest <= cfg.CANONICAL_MAX_SIDE:
        return bgr
    scale = cfg.CANONICAL_MAX_SIDE / longest
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return cv2.resize(bgr, size, interpolation=getattr(cv2, cfg.CANONICAL_INTERPOLATION))


def decode_image(image_b64: str) -> np.ndarray:
    """Base64 string or data URL -> BGR uint8 array at the canonical resolution."""
    if not isinstance(image_b64, str):
        raise ImageRejected([UNREADABLE])
    text = image_b64.strip()
    prefix = _DATA_URL_PREFIX.match(text)
    if prefix:
        text = text[prefix.end() :]
    try:
        raw = base64.b64decode("".join(text.split()), validate=True)
    except (binascii.Error, ValueError):
        raise ImageRejected([UNREADABLE]) from None
    if not raw:
        raise ImageRejected([UNREADABLE])

    # Read only the header first, so a small file that declares enormous dimensions
    # (a decompression bomb) is refused before any pixel memory is allocated.
    try:
        with Image.open(io.BytesIO(raw), formats=cfg.ALLOWED_FORMATS) as header:
            width, height = header.size
    except Image.DecompressionBombError:  # Pillow's own, even larger, limit
        raise ImageRejected([TOO_LARGE]) from None
    except (UnidentifiedImageError, OSError):
        raise ImageRejected([UNREADABLE]) from None
    if width * height > cfg.MAX_IMAGE_PIXELS:
        raise ImageRejected([TOO_LARGE])

    bgr = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if bgr is None:
        raise ImageRejected([UNREADABLE])

    return to_canonical_resolution(bgr)  # early, so a big photo's pixels are freed at once
