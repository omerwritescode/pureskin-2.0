"""POST /api/scan/analyze: image + questionnaire -> merged Skin Profile, in memory."""

import base64
import io
import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.api import image_analysis as image_endpoint
from app.api import scan_analyze
from app.services.image_analysis import ImageRejected, ModelUnavailable
from app.services.image_analysis import scoring_config as image_cfg
from app.services.image_analysis.tests.conftest import (
    sample_photos,
    shapes_image,
    to_data_url,
)
from app.services.skin_profile import ScoreSources, reproduce_final

URL = "/api/scan/analyze"
PROFILE_KEYS = {"acne_score", "redness_score", "wrinkle_score", "pigmentation_score", "pore_score",
                "skin_type"}
SECRET = "zzqx-private-free-text-marker"
IMAGE = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8 not really a jpeg " * 50).decode()
FINGERPRINT = IMAGE[40:90]

CURRENT_ANSWERS = {  # what the step 5 funnel sends today
    "skin_type": "combination", "primary_concern": "acne", "sensitivities": [],
    "sensitivities_other": "", "current_products": [], "current_products_other": "",
    "sleep": "6_to_8", "stress": "medium",
}


def image_result(**scores) -> dict:
    """A stand-in for analyze_image(): it even 'predicts' a skin type, which must be ignored."""
    values = {"acne_score": 30, "redness_score": 40, "wrinkle_score": 50,
              "pigmentation_score": 60, "pore_score": 70, **scores}
    return {
        **values,
        "skin_type_prediction": "oily",
        "skin_type_confidence": 0.99,
        "skin_type_labels_supported": ["dry", "normal", "oily"],
        "quality": {"ok": True, "issues": ["Smiling deepens the lines around your eyes."]},
        "model_version": "image-analysis-1.0.0+heuristic-1+skin-type-test",
    }


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(scan_analyze.router)
    app.include_router(image_endpoint.router)
    return TestClient(app)


@pytest.fixture
def fake_image(monkeypatch):
    """Replace the image analyzer; records every call."""
    calls = []

    def install(result=None, raises=None):
        def fake(image):
            calls.append(image)
            if raises:
                raise raises
            return result or image_result()

        monkeypatch.setattr(scan_analyze, "analyze_image", fake)
        return calls

    return install


def post(client, answers=None, **extra):
    return client.post(URL, json={"image": IMAGE, "answers": answers or {}, **extra})


# --------------------------------------------------------------------------------------
# Successful merge
# --------------------------------------------------------------------------------------


def test_returns_the_profile_keys_plus_the_extras(client, fake_image):
    fake_image()
    response = post(client, CURRENT_ANSWERS)
    assert response.status_code == 200
    body = response.json()
    assert PROFILE_KEYS <= set(body)
    assert set(body) == PROFILE_KEYS | {"is_sensitive", "score_sources", "sources", "quality"}
    for name in PROFILE_KEYS - {"skin_type"}:
        assert isinstance(body[name], int) and 1 <= body[name] <= 100
    ScoreSources.model_validate(body["score_sources"])
    assert body["quality"] == {"ok": True, "issues": ["Smiling deepens the lines around your eyes."]}


def test_scores_reproduce_from_score_sources(client, fake_image):
    fake_image(image_result(acne_score=95, pigmentation_score=66))
    body = post(client, {"breakouts": "most_weeks", "dark_spots": "a_few"}).json()
    for name, entry in body["score_sources"]["scores"].items():
        assert reproduce_final(name, entry) == body[name]


def test_todays_answers_give_image_scores_with_acne_capped(client, fake_image):
    fake_image(image_result(acne_score=85, redness_score=72))
    body = post(client, CURRENT_ANSWERS).json()
    assert body["acne_score"] == 60  # the image alone can't reach the > 60 acne step
    assert body["redness_score"] == 72
    acne = body["score_sources"]["scores"]["acne_score"]
    assert (acne["method"], acne["questionnaire"], acne["capped"]) == ("image", None, True)
    assert body["sources"]["acne_score"].startswith("image only, capped at 60")


def test_skin_type_and_sensitivity_come_from_the_questionnaire_only(client, fake_image):
    fake_image()  # the image "predicts" oily with 0.99 confidence
    body = post(client, {"skin_type": "dry"}).json()
    assert (body["skin_type"], body["is_sensitive"]) == ("dry", False)
    assert body["score_sources"]["skin_type"] == "questionnaire"
    body = post(client, {"skin_type": "sensitive"}).json()
    assert (body["skin_type"], body["is_sensitive"]) == ("normal", True)
    assert body["score_sources"]["skin_type"] == "default"
    assert "skin_type_prediction" not in json.dumps(body) and "0.99" not in json.dumps(body)


def test_primary_concern_never_nudges_a_score(client, fake_image):
    """The stated concern is a goal, not a measurement: it never moves a score."""
    fake_image()
    bodies = [post(client, {**CURRENT_ANSWERS, "primary_concern": c}).json()
              for c in ("acne", "redness", "wrinkles", "pigmentation", "pores", "none")]
    assert all(b == bodies[0] for b in bodies)


# --------------------------------------------------------------------------------------
# Errors: 422 passthrough, 413, 503 without fallback, no bypass switch
# --------------------------------------------------------------------------------------


def test_image_rejection_passes_through_as_422(client, fake_image):
    issues = ["The lighting is too dim for an accurate result. Please retake the photo."]
    fake_image(raises=ImageRejected(issues))
    response = post(client, CURRENT_ANSWERS)
    assert response.status_code == 422
    assert response.json() == {"quality": {"ok": False, "issues": issues}}


def test_real_rejection_has_the_image_endpoints_shape(client):
    try:
        from app.services.image_analysis import load_models
        load_models()
    except ModelUnavailable as exc:
        pytest.skip(f"face model not downloaded: {exc}")
    image = to_data_url(shapes_image())  # no face in it
    ours = client.post(URL, json={"image": image, "answers": CURRENT_ANSWERS})
    theirs = client.post("/api/services/image/analyze", json={"image": image})
    assert ours.status_code == theirs.status_code == 422
    assert ours.json() == theirs.json()


def test_model_unavailable_is_503_with_no_fallback_scores(client, fake_image):
    fake_image(raises=ModelUnavailable("Face landmark model not found. Download it with ..."))
    response = post(client, CURRENT_ANSWERS)
    assert response.status_code == 503
    assert set(response.json()) == {"detail"}
    assert "Download it" in response.json()["detail"]


def test_oversized_body_is_413(client, fake_image):
    calls = fake_image()
    response = client.post(URL, content=b"x" * (image_cfg.MAX_REQUEST_BYTES + 1),
                           headers={"content-type": "application/json"})
    assert response.status_code == 413
    assert response.json()["detail"] == image_endpoint.TOO_LARGE
    assert calls == []


def test_oversized_chunked_body_is_413(client, fake_image):
    fake_image()

    def chunks():
        for _ in range(image_cfg.MAX_REQUEST_BYTES // 65_536 + 2):
            yield b"x" * 65_536

    response = client.post(URL, content=chunks(), headers={"content-type": "application/json"})
    assert response.status_code == 413


@pytest.mark.parametrize(
    "extra",
    [{"lighting_gate": False}, {"debug": True}, {"skip_quality": True}, {"options": {}}],
)
def test_no_bypass_or_extra_parameter_is_accepted(client, fake_image, extra):
    calls = fake_image()
    response = post(client, CURRENT_ANSWERS, **extra)
    assert response.status_code == 422
    assert calls == []  # rejected before any analysis


def test_bad_answers_are_rejected_before_the_photo_is_analysed(client, fake_image):
    calls = fake_image()
    response = post(client, {"skin_type": "purple"})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "answers", "skin_type"]
    assert calls == []


@pytest.mark.parametrize(
    "content",
    [
        json.dumps({"image": IMAGE, "answers": {"sensitivities_other": SECRET * 30}}).encode(),
        json.dumps({"image": IMAGE, "answers": {"current_products_other": SECRET,
                                                "stress": "extreme"}}).encode(),
        json.dumps({"image": IMAGE, "answers": {"skin_type": SECRET}}).encode(),
        json.dumps({"image": [IMAGE], "answers": {"sensitivities_other": SECRET}}).encode(),
        json.dumps({"image": IMAGE, "answers": SECRET}).encode(),
        json.dumps({"image": IMAGE, "answers": {}, "note": SECRET}).encode(),
        b'{"image": "' + IMAGE.encode() + b'", "answers": {"sensitivities_other": "' + SECRET.encode(),
    ],
)
def test_malformed_body_422_contains_neither_image_nor_free_text(client, fake_image, caplog, content):
    calls = fake_image()
    with caplog.at_level(logging.DEBUG):
        response = client.post(URL, content=content, headers={"content-type": "application/json"})
    assert response.status_code == 422
    assert "detail" in response.json()
    for secret in (FINGERPRINT, SECRET):
        assert secret not in response.text
        assert secret not in caplog.text
    assert calls == []


def test_success_response_contains_no_free_text(client, fake_image, caplog):
    fake_image()
    answers = {**CURRENT_ANSWERS, "sensitivities_other": f"lanolin {SECRET}",
               "current_products_other": SECRET}
    with caplog.at_level(logging.DEBUG):
        response = post(client, answers)
    assert response.status_code == 200
    assert SECRET not in response.text and SECRET not in caplog.text
    assert FINGERPRINT not in response.text


# --------------------------------------------------------------------------------------
# Real selfies (skipped when samples/ is empty)
# --------------------------------------------------------------------------------------


def funnel_data_url(path, max_side=720, quality=85) -> str:
    """The selfie page's downsizing: longest side <= 720 px, JPEG quality 0.85."""
    img = Image.open(path).convert("RGB")
    scale = min(1, max_side / max(img.size))
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.BILINEAR)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def test_real_selfies_end_to_end(client):
    photos = sample_photos()
    if not photos:
        pytest.skip("no sample selfies in image_analysis/samples/")
    for path in photos:
        image = funnel_data_url(path)
        first = client.post(URL, json={"image": image, "answers": CURRENT_ANSWERS})
        if first.status_code == 503:
            pytest.skip("face model not downloaded")
        assert first.status_code == 200, (path.name, first.text)
        body = first.json()
        ScoreSources.model_validate(body["score_sources"])
        image_only = client.post("/api/services/image/analyze", json={"image": image}).json()
        # Today's answers carry no score evidence: image scores, acne capped at 60.
        for name in ("redness_score", "wrinkle_score", "pigmentation_score", "pore_score"):
            assert body[name] == image_only[name]
        assert body["acne_score"] == min(image_only["acne_score"], 60)
        assert body["skin_type"] == "combination"
        second = client.post(URL, json={"image": image, "answers": CURRENT_ANSWERS})
        assert second.json() == body  # deterministic
