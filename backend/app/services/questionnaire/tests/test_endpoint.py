import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.questionnaire import router
from app.services.questionnaire import questionnaire_config as cfg

URL = "/api/services/questionnaire/score"
SECRET = "zzqx-private-free-text-marker"


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def post_raw(client, content: bytes):
    return client.post(URL, content=content, headers={"content-type": "application/json"})


def test_scores_valid_answers(client):
    response = client.post(URL, json={"skin_type": "oily", "breakouts": "constantly"})
    assert response.status_code == 200
    body = response.json()
    assert body["skin_type"] == "oily"
    assert body["estimates"]["acne_score"] == 75
    assert body["config_version"] == cfg.CONFIG_VERSION


def test_empty_object_is_valid(client):
    response = client.post(URL, json={})
    assert response.status_code == 200
    assert set(response.json()["estimates"].values()) == {None}


@pytest.mark.parametrize(
    "body",
    [
        {"skin_type": "purple"},
        {"unknown_key": 1},
        {"sensitivities": ["gluten"]},
        {"sensitivities_other": "x" * (cfg.MAX_FREE_TEXT_CHARS + 1)},
    ],
)
def test_bad_answers_are_a_clear_422(client, body):
    response = client.post(URL, json=body)
    assert response.status_code == 422
    errors = response.json()["detail"]
    assert errors and all({"loc", "msg", "type"} == set(e) for e in errors)
    assert errors[0]["loc"][0] == "body"


@pytest.mark.parametrize("content", [b"not json", b"[1, 2]", b'"oily"', b"null", b""])
def test_non_object_bodies_are_422(client, content):
    assert post_raw(client, content).status_code == 422


def test_oversized_body_is_413(client):
    assert post_raw(client, b"x" * (cfg.MAX_REQUEST_BYTES + 1)).status_code == 413


@pytest.mark.parametrize(
    "content",
    [
        # Free text too long: FastAPI's default 422 would echo the whole text.
        json.dumps({"sensitivities_other": SECRET * 40}).encode(),
        # Free text in the wrong type of field.
        json.dumps({"skin_type": SECRET, "sleep": SECRET}).encode(),
        json.dumps({"sensitivities": [SECRET]}).encode(),
        # Valid free text next to an invalid answer.
        json.dumps({"current_products_other": SECRET, "stress": "extreme"}).encode(),
        # Broken JSON.
        b'{"sensitivities_other": "' + SECRET.encode() + b'"',
    ],
)
def test_errors_never_echo_free_text(client, caplog, content):
    with caplog.at_level(logging.DEBUG):
        response = post_raw(client, content)
    assert response.status_code == 422
    assert SECRET not in response.text
    assert SECRET not in caplog.text


def test_unknown_keys_are_truncated_in_errors(client):
    response = client.post(URL, json={SECRET * 10: "x"})
    assert response.status_code == 422
    assert SECRET * 3 not in response.text


def test_success_response_has_no_free_text(client, caplog):
    with caplog.at_level(logging.DEBUG):
        response = client.post(
            URL, json={"sensitivities_other": f"lanolin {SECRET}", "current_products_other": SECRET}
        )
    assert response.status_code == 200
    assert SECRET not in response.text and SECRET not in caplog.text
    assert response.json()["avoid"] == ["lanolin"]
