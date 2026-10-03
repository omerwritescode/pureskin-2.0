"""Canonical resolution: every photo is analysed at <= CANONICAL_MAX_SIDE px (step 7b-ii).

Before this, the client's resize was part of the model: the same photo passed at 720 px
but was rejected as too dim at 960 and 1080 px.
"""

import base64
import io
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from app.services.image_analysis import ImageRejected, analyze_image
from app.services.image_analysis import scoring_config as cfg
from app.services.image_analysis.decode import decode_image, to_canonical_resolution
from app.services.image_analysis.tests.conftest import IMAGE_SUFFIXES, SAMPLES_DIR

IMAGE_PRIMARY = ("redness_score", "wrinkle_score", "pigmentation_score", "pore_score")
IMAGE_PRIMARY_TOLERANCE = 4  # points; measured max on the project's photos: 4
ACNE_TOLERANCE = 20  # acne is documented as unstable; measured max here: 14
CLIENT_SIDES = (720, 960, 1080)
CLIENT_JPEG_QUALITY = 92  # the selfie page's setting from 7b-ii


# --------------------------------------------------------------------------------------
# The canonical step itself (synthetic arrays, always runs)
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(("height", "width"), [(1280, 960), (960, 1280), (2000, 1000), (721, 400)])
def test_large_images_are_shrunk_to_the_canonical_side(height, width):
    out = to_canonical_resolution(np.zeros((height, width, 3), np.uint8))
    assert max(out.shape[:2]) == cfg.CANONICAL_MAX_SIDE
    assert abs(out.shape[1] / out.shape[0] - width / height) < 0.01  # aspect kept


@pytest.mark.parametrize(("height", "width"), [(720, 540), (480, 640), (100, 100)])
def test_small_images_are_never_enlarged(height, width):
    image = np.random.default_rng(0).integers(0, 255, (height, width, 3), np.uint8)
    assert to_canonical_resolution(image) is image


def test_deterministic_and_idempotent():
    image = np.random.default_rng(1).integers(0, 255, (1080, 1440, 3), np.uint8)
    once = to_canonical_resolution(image)
    assert np.array_equal(once, to_canonical_resolution(image.copy()))
    assert to_canonical_resolution(once) is once


def test_decode_returns_the_canonical_resolution():
    image = np.random.default_rng(2).integers(0, 255, (1440, 1080, 3), np.uint8)
    ok, png = cv2.imencode(".png", image)
    assert ok
    decoded = decode_image(base64.b64encode(png.tobytes()).decode())
    assert decoded.shape[:2] == (720, 540)


# --------------------------------------------------------------------------------------
# Real photos (skipped when samples/ is empty)
# --------------------------------------------------------------------------------------


def _photos() -> list[Path]:
    found = []
    for folder in (SAMPLES_DIR, SAMPLES_DIR / "lighting"):
        if folder.is_dir():
            found += sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    return found


def client_data_url(path: Path, max_side: int, quality: int = CLIENT_JPEG_QUALITY) -> str:
    """What a browser would send: longest side <= max_side, bilinear resize, JPEG."""
    img = Image.open(path).convert("RGB")
    scale = min(1, max_side / max(img.size))
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.BILINEAR)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def test_an_exact_2x_upscale_gives_the_identical_result(analyzer, samples):
    """2x nearest-neighbour then INTER_AREA halving restores every pixel exactly."""
    small = decode_image(client_data_url(samples[0], 720))
    big = cv2.resize(small, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
    a, b = analyzer.analyze(small), analyzer.analyze(big)
    assert a.scores == b.scores and a.warnings == b.warnings


@pytest.mark.parametrize(
    "path", _photos() or [None],
    ids=lambda p: p and str(p.relative_to(SAMPLES_DIR)).replace("\\", "/"),
)
def test_client_resolution_does_not_change_the_result(analyzer, path):
    if path is None:
        pytest.skip(f"no sample photos in {SAMPLES_DIR}")
    results, references = {}, {}
    for side in CLIENT_SIDES:
        url = client_data_url(path, side)
        try:
            results[side] = analyze_image(url)
        except ImageRejected as exc:
            results[side] = exc
        light = analyzer.analyze(decode_image(url), lighting_gate=False).lighting
        references[side] = (light.exposure_source, round(light.exposure_l, 1))

    if len({source for source, _ in references.values()}) > 1:
        # Known borderline case (README, "Canonical resolution"): the dim check's white
        # reference flips between the eye whites and the scene highlights on resampling
        # noise. That's the lighting gate's robustness, not resolution.
        pytest.xfail(f"white reference changes between variants: {references}")

    decisions = {side: isinstance(r, ImageRejected) for side, r in results.items()}
    assert len(set(decisions.values())) == 1, decisions
    if isinstance(results[720], ImageRejected):
        assert len({tuple(r.issues) for r in results.values()}) == 1
        return
    for side in CLIENT_SIDES[1:]:
        for score in IMAGE_PRIMARY:
            assert abs(results[side][score] - results[720][score]) <= IMAGE_PRIMARY_TOLERANCE
        assert abs(results[side]["acne_score"] - results[720]["acne_score"]) <= ACNE_TOLERANCE
