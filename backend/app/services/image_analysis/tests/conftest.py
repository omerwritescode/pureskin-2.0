import base64
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.services.image_analysis import ModelUnavailable, load_models

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def sample_photos() -> list[Path]:
    """Your own selfies dropped into samples/ (top level only; gitignored)."""
    if not SAMPLES_DIR.is_dir():
        return []
    return sorted(p for p in SAMPLES_DIR.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)


def to_data_url(bgr: np.ndarray, quality: int = 85) -> str:
    ok, jpeg = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    assert ok
    return "data:image/jpeg;base64," + base64.b64encode(jpeg.tobytes()).decode()


def shapes_image(seed: int = 0, low: int = 40, high: int = 230) -> np.ndarray:
    """Sharp, well-exposed, colourful rectangles and circles: no face in it."""
    rng = np.random.default_rng(seed)
    image = np.full((480, 640, 3), (low + high) // 2, dtype=np.uint8)
    for _ in range(60):
        colour = tuple(int(c) for c in rng.integers(low, high, 3))
        x, y = int(rng.integers(0, 640)), int(rng.integers(0, 480))
        if rng.random() < 0.5:
            cv2.rectangle(
                image,
                (x, y),
                (x + int(rng.integers(10, 120)), y + int(rng.integers(10, 120))),
                colour,
                -1,
            )
        else:
            cv2.circle(image, (x, y), int(rng.integers(5, 60)), colour, -1)
    return image


@pytest.fixture(scope="session")
def analyzer():
    try:
        return load_models()
    except ModelUnavailable as exc:
        pytest.skip(f"face model not downloaded: {exc}")


@pytest.fixture(scope="session")
def samples() -> list[Path]:
    photos = sample_photos()
    if not photos:
        pytest.skip(f"no sample selfies in {SAMPLES_DIR} (see README.md, 'Testing')")
    return photos
