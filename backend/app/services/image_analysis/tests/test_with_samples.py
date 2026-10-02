"""Tests that need a real face: your own selfies in samples/ (gitignored).

All of these skip when samples/ is empty. See README.md, "Testing".
"""

import base64

import cv2
import numpy as np
import pytest

from app.services.image_analysis import ImageRejected, analyze_image, quality, scoring

from .conftest import to_data_url


def _load(path) -> np.ndarray:
    image = cv2.imread(str(path))
    assert image is not None, f"unreadable sample: {path}"
    return image


def _file_b64(path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


def _srgb_to_linear(bgr: np.ndarray) -> np.ndarray:
    return scoring._srgb_to_linear(bgr.astype(np.float32) / 255.0)


def _linear_to_bgr(linear: np.ndarray) -> np.ndarray:
    linear = np.clip(linear, 0.0, 1.0)
    srgb = np.where(linear <= 0.0031308, linear * 12.92, 1.055 * linear ** (1 / 2.4) - 0.055)
    return np.clip(srgb * 255.0 + 0.5, 0, 255).astype(np.uint8)


def _inject(bgr: np.ndarray, analyzer, absorb_bgr: tuple[float, float, float], strength: float):
    """Paint small synthetic lesions (Gaussian absorption, ~3.5 mm across) at fixed
    cheek/forehead/chin landmarks, in linear light."""
    face = analyzer.face_detector.detect(bgr)[0]
    sites = [50, 205, 280, 425, 108, 151, 337, 69, 299, 200, 199, 421, 201]
    height, width = bgr.shape[:2]
    ys, xs = np.mgrid[0:height, 0:width]
    sigma = 0.025 * face.width / 2.5
    profile = np.zeros((height, width), np.float32)
    for x, y in face.points[sites]:
        profile = np.maximum(profile, np.exp(-((xs - x) ** 2 + (ys - y) ** 2) / (2 * sigma**2)))
    linear = _srgb_to_linear(bgr)
    for channel, absorb in enumerate(absorb_bgr):
        linear[..., channel] *= np.exp(-strength * absorb * profile)
    return _linear_to_bgr(linear)


def test_samples_score_within_contract(samples):
    for path in samples:
        result = analyze_image(_file_b64(path))
        assert set(result) >= {
            "acne_score",
            "redness_score",
            "wrinkle_score",
            "pigmentation_score",
            "pore_score",
            "skin_type_prediction",
            "skin_type_confidence",
            "quality",
            "model_version",
        }, path.name
        for name in scoring.SCORE_NAMES:
            assert isinstance(result[name], int) and 1 <= result[name] <= 100, (path.name, name)
        assert result["quality"]["ok"] is True
        assert all(isinstance(issue, str) for issue in result["quality"]["issues"])
        assert isinstance(result["model_version"], str) and result["model_version"]


def test_samples_are_deterministic(samples):
    image = _file_b64(samples[0])
    assert analyze_image(image) == analyze_image(image)


def test_darkened_sample_rejected_as_too_dark(samples):
    dark = _linear_to_bgr(_srgb_to_linear(_load(samples[0])) * 0.005)
    with pytest.raises(ImageRejected) as exc_info:
        analyze_image(to_data_url(dark))
    assert quality.TOO_DARK in exc_info.value.issues


def test_blurred_sample_rejected_as_blurry(samples):
    image = _load(samples[0])
    blurred = cv2.GaussianBlur(image, (0, 0), max(image.shape[:2]) / 120)
    with pytest.raises(ImageRejected) as exc_info:
        analyze_image(to_data_url(blurred))
    assert quality.BLURRY in exc_info.value.issues


def test_synthetic_red_papules_raise_acne_score(samples, analyzer):
    image = _load(samples[0])
    clean = analyze_image(to_data_url(image))["acne_score"]
    spotty = analyze_image(to_data_url(_inject(image, analyzer, (0.8, 1.0, 0.1), 0.35)))[
        "acne_score"
    ]
    assert spotty > clean or clean >= 95


def test_synthetic_brown_spots_raise_pigmentation_score(samples, analyzer):
    image = _load(samples[0])
    clean = analyze_image(to_data_url(image))["pigmentation_score"]
    spotty = analyze_image(to_data_url(_inject(image, analyzer, (1.5, 1.3, 1.0), 0.4)))[
        "pigmentation_score"
    ]
    assert spotty > clean or clean >= 95


def _half_face_shadow(bgr: np.ndarray, analyzer, shade: float = 0.3) -> np.ndarray:
    """Light falling from one side: the face's left half at `shade` of the right half's
    brightness (linear light), with a soft transition down the middle of the face."""
    from app.services.image_analysis.regions import FACE_OVAL

    face = analyzer.face_detector.detect(bgr)[0]
    centre = float(face.points[FACE_OVAL][:, 0].mean())
    xs = np.arange(bgr.shape[1], dtype=np.float32)
    gain = shade + (1 - shade) / (1 + np.exp(-(xs - centre) / (0.05 * face.width)))
    return _linear_to_bgr(_srgb_to_linear(bgr) * gain[None, :, None])


def test_half_face_shadow_rejected_as_uneven_light(samples, analyzer):
    with pytest.raises(ImageRejected) as exc_info:
        analyze_image(to_data_url(_half_face_shadow(_load(samples[0]), analyzer)))
    assert quality.UNEVEN_LIGHT in exc_info.value.issues


def test_analysis_mode_scores_what_the_gate_rejects(samples, analyzer):
    shadowed = _half_face_shadow(_load(samples[0]), analyzer)
    result = analyzer.analyze(shadowed, lighting_gate=False)
    assert quality.UNEVEN_LIGHT in result.warnings
    assert all(1 <= result.scores[n] <= 100 for n in scoring.SCORE_NAMES)


def test_endpoint_cannot_switch_the_gate_off(samples, analyzer):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.image_analysis import router

    app = FastAPI()
    app.include_router(router)
    image = to_data_url(_half_face_shadow(_load(samples[0]), analyzer))
    response = TestClient(app).post(
        "/api/services/image/analyze", json={"image": image, "lighting_gate": False}
    )
    assert response.status_code == 422
    assert quality.UNEVEN_LIGHT in response.json()["quality"]["issues"]
