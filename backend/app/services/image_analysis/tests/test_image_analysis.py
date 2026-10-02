"""Image Analysis service: rejections, score range, output contract, endpoint, privacy.

Everything here runs on synthetic images generated in code. Tests that need a real face
are in test_with_samples.py.
"""

import base64
import builtins
import logging
import struct
import tempfile
import time
import zlib

import cv2
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.api.image_analysis import ImageAnalysisResponse, router
from app.services.image_analysis import ImageRejected, analyze_image, decode, quality, scoring
from app.services.image_analysis import scoring_config as cfg
from app.services.image_analysis.analyzer import AnalysisResult

from .conftest import shapes_image, to_data_url

CONTRACT_KEYS = {
    "acne_score",
    "redness_score",
    "wrinkle_score",
    "pigmentation_score",
    "pore_score",
    "skin_type_prediction",
    "skin_type_confidence",
    "skin_type_labels_supported",
    "quality",
    "model_version",
}


def rejection_issues(image_b64: str) -> list[str]:
    with pytest.raises(ImageRejected) as exc_info:
        analyze_image(image_b64)
    return exc_info.value.issues


# --------------------------------------------------------------------------------------
# Hard rejections (synthetic images)
# --------------------------------------------------------------------------------------


def test_no_face_rejected(analyzer):
    assert rejection_issues(to_data_url(shapes_image())) == [quality.NO_FACE]


def test_too_dark_rejected(analyzer):
    dark = (shapes_image().astype(np.float32) * 0.08).astype(np.uint8)  # brightest ~18/255
    assert rejection_issues(to_data_url(dark)) == [quality.TOO_DARK]


def test_overexposed_rejected(analyzer):
    washed_out = shapes_image(low=248, high=256)
    assert rejection_issues(to_data_url(washed_out)) == [quality.OVEREXPOSED]


def test_blurry_rejected(analyzer):
    blurry = cv2.GaussianBlur(shapes_image(), (0, 0), 8)
    assert rejection_issues(to_data_url(blurry)) == [quality.BLURRY]


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "   ",
        "not base64 at all!",
        base64.b64encode(b"plain text, not an image").decode(),
        "data:image/jpeg;base64,",
        12345,
    ],
)
def test_unreadable_input_rejected(payload):
    with pytest.raises(ImageRejected) as exc_info:
        decode.decode_image(payload)
    assert exc_info.value.issues == [decode.UNREADABLE]


def test_decompression_bomb_refused_before_decoding():
    """A tiny PNG whose header claims 50000 x 50000 px must be refused from the header
    alone, without allocating the ~7.5 GB the pixels would need."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 50_000, 50_000, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00" * 64))
        + chunk(b"IEND", b"")
    )
    started = time.perf_counter()
    with pytest.raises(ImageRejected) as exc_info:
        decode.decode_image(base64.b64encode(png).decode())
    assert exc_info.value.issues == [decode.TOO_LARGE]
    assert time.perf_counter() - started < 1.0


def test_data_url_and_bare_base64_decode_the_same():
    url = to_data_url(shapes_image())
    bare = url.split(",", 1)[1]
    assert np.array_equal(decode.decode_image(url), decode.decode_image(bare))


# --------------------------------------------------------------------------------------
# Score range and output contract
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("anchor", sorted(cfg.SCORE_ANCHORS))
@pytest.mark.parametrize("raw", [-np.inf, -1e9, -1.0, 0.0, 1e-6, 0.5, 1.0, 1e9, np.inf])
def test_every_raw_feature_maps_into_1_to_100(anchor, raw):
    score = scoring.clamp_score(scoring._interp(raw, anchor))
    assert isinstance(score, int) and 1 <= score <= 100


@pytest.mark.parametrize("value", [-1e9, -0.4, 0.0, 0.5, 1.49, 99.5, 100.4, 1e9])
def test_clamp_score_always_in_range(value):
    score = scoring.clamp_score(value)
    assert isinstance(score, int) and 1 <= score <= 100


def test_nan_feature_raises_instead_of_inventing_a_score():
    with pytest.raises(ValueError):
        scoring._interp(float("nan"), "acne")


def test_anchors_are_increasing():
    for name, (xs, ys) in cfg.SCORE_ANCHORS.items():
        assert list(xs) == sorted(xs) and list(ys) == sorted(ys), name
        assert ys[0] >= 1 and ys[-1] <= 100, name


def test_response_shape_matches_contract():
    result = AnalysisResult(
        scores={name: 50 for name in scoring.SCORE_NAMES},
        warnings=["Lighting is dim, so scores may be less accurate."],
        model_version="test",
    )
    response = result.to_response()
    assert set(response) == CONTRACT_KEYS
    assert response["skin_type_prediction"] is None
    assert response["skin_type_confidence"] is None
    assert response["skin_type_labels_supported"] == []
    assert response["quality"] == {"ok": True, "issues": result.warnings}
    ImageAnalysisResponse.model_validate(response)  # the endpoint's own schema


# --------------------------------------------------------------------------------------
# Endpoint
# --------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


URL = "/api/services/image/analyze"


def test_endpoint_rejection_is_422_with_issues_and_no_scores(client, analyzer):
    response = client.post(URL, json={"image": to_data_url(shapes_image())})
    assert response.status_code == 422
    assert response.json() == {"quality": {"ok": False, "issues": [quality.NO_FACE]}}


def test_endpoint_refuses_oversized_body(client):
    response = client.post(
        URL,
        content=b"x" * (cfg.MAX_REQUEST_BYTES + 1),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413
    assert "720" in response.json()["detail"]


def test_endpoint_refuses_oversized_chunked_body(client):
    """No Content-Length header: the limit must still hold while streaming."""

    def chunks():
        for _ in range(cfg.MAX_REQUEST_BYTES // 65_536 + 2):
            yield b"x" * 65_536

    response = client.post(URL, content=chunks(), headers={"content-type": "application/json"})
    assert response.status_code == 413


@pytest.mark.parametrize(
    "body", [b"not json", b"[]", b'{"img": "abc"}', b'{"image": 42}', b'{"image": ""}']
)
def test_endpoint_malformed_request_is_400(client, body):
    response = client.post(URL, content=body, headers={"content-type": "application/json"})
    assert response.status_code == 400


# --------------------------------------------------------------------------------------
# Privacy
# --------------------------------------------------------------------------------------


def test_analysis_never_writes_files(analyzer, monkeypatch):
    """Decode + checks + face detection must stay in memory. (Native MediaPipe code
    can't be intercepted from Python; it is only given an in-memory array.)"""

    def forbidden(*args, **kwargs):
        raise AssertionError("image analysis tried to write to disk")

    real_open = builtins.open

    def guarded_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wax+"):
            forbidden()
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(cv2, "imwrite", forbidden)
    monkeypatch.setattr(Image.Image, "save", forbidden)
    for name in (
        "NamedTemporaryFile",
        "TemporaryFile",
        "SpooledTemporaryFile",
        "mkstemp",
        "mkdtemp",
    ):
        monkeypatch.setattr(tempfile, name, forbidden)

    with pytest.raises(ImageRejected):
        analyze_image(to_data_url(shapes_image()))


def test_image_data_never_logged_or_echoed(client, analyzer, caplog):
    image = to_data_url(shapes_image(seed=3))
    fingerprint = image[200:260]
    with caplog.at_level(logging.DEBUG):
        responses = [
            client.post(URL, json={"image": image}),  # rejected photo
            client.post(
                URL,
                content=b'{"image": "' + image.encode() + b'"',
                headers={"content-type": "application/json"},
            ),  # broken JSON
        ]
    assert fingerprint not in caplog.text
    for response in responses:
        assert fingerprint not in response.text


# --------------------------------------------------------------------------------------
# Missing model
# --------------------------------------------------------------------------------------


def test_missing_face_model_gives_clear_error(tmp_path):
    from app.services.image_analysis import ModelUnavailable
    from app.services.image_analysis.analyzer import ImageAnalyzer

    with pytest.raises(ModelUnavailable) as exc_info:
        ImageAnalyzer(tmp_path / "face_landmarker.task")
    assert "download_models" in str(exc_info.value)


def test_endpoint_returns_503_when_model_missing(client, monkeypatch):
    from app.api import image_analysis as endpoint
    from app.services.image_analysis import ModelUnavailable

    def unavailable(_image):
        raise ModelUnavailable("Face landmark model not found. Download it with ...")

    monkeypatch.setattr(endpoint, "analyze_image", unavailable)
    response = client.post(URL, json={"image": to_data_url(shapes_image())})
    assert response.status_code == 503
    assert "Download it" in response.json()["detail"]


# --------------------------------------------------------------------------------------
# Lighting gate (dim / uneven light are hard rejections)
# --------------------------------------------------------------------------------------


def _light(exposure_l=85.0, side_ratio=1.1):
    from app.services.image_analysis.lighting import Lighting

    return Lighting(exposure_l, "eye whites", side_ratio, 0.7)


@pytest.mark.parametrize(
    ("light", "expected"),
    [
        (_light(), []),
        (_light(exposure_l=cfg.DIM_MIN_EXPOSURE_L - 0.1), [quality.TOO_DARK]),
        (_light(exposure_l=cfg.DIM_MIN_EXPOSURE_L), []),
        (_light(side_ratio=cfg.UNEVEN_LIGHT_MAX_RATIO + 0.01), [quality.UNEVEN_LIGHT]),
        (_light(side_ratio=cfg.UNEVEN_LIGHT_MAX_RATIO), []),
        (_light(side_ratio=None), []),  # a cheek hidden: evenness can't be judged
        (
            _light(exposure_l=cfg.DIM_MIN_EXPOSURE_L - 5, side_ratio=3.0),
            [quality.TOO_DARK, quality.UNEVEN_LIGHT],
        ),
    ],
)
def test_lighting_decision(light, expected):
    assert quality.check_lighting(light) == expected


def test_lighting_messages_ask_politely_for_a_retake():
    for message in quality.LIGHTING_ISSUES:
        assert "Please retake" in message


def test_public_interface_has_no_way_to_turn_the_gate_off():
    import inspect

    assert list(inspect.signature(analyze_image).parameters) == ["image_b64"]
