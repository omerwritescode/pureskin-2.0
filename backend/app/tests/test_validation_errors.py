"""The global 422 handler (main.py) and the shared sanitizer never echo submitted input.

These requests all fail validation, so they never reach the database.
"""

import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.api.validation_errors import GENERIC_MSG, public_errors
from app.main import app

# Distinctive values, so a match in the response can only be an echo.
PASSWORD = "Zq9#Kw7"  # 7 characters: too short
LONG_PASSWORD = "Zq9#Kw7-echo-probe-" + "p" * 60  # over bcrypt's 72 bytes
EMAIL = "pw.echo.probe.5821@example.com"
BAD_EMAIL = "zq.echo<probe>.5821@example.com"


@pytest.fixture(scope="module")
def client():
    return TestClient(app)  # no `with`: the image model isn't needed for 422s


def assert_no_echo(response, *secrets):
    assert response.status_code == 422
    for secret in secrets:
        assert secret not in response.text, f"{secret!r} echoed in {response.text}"
    for error in response.json()["detail"]:
        assert set(error) <= {"loc", "msg", "type", "ctx"}
        assert "input" not in error


# --------------------------------------------------------------------------------------
# Register and login
# --------------------------------------------------------------------------------------


def test_register_short_password(client):
    response = client.post(
        "/api/auth/register", json={"email": EMAIL, "password": PASSWORD, "full_name": "Echo Probe"}
    )
    assert_no_echo(response, PASSWORD, EMAIL)
    assert response.json() == {
        "detail": [{
            "loc": ["body", "password"],
            "msg": "String should have at least 8 characters",
            "type": "string_too_short",
            "ctx": {"min_length": 8},
        }]
    }


def test_register_bad_email(client):
    response = client.post(
        "/api/auth/register",
        json={"email": BAD_EMAIL, "password": PASSWORD + "-long-enough", "full_name": "Echo Probe"},
    )
    assert_no_echo(response, BAD_EMAIL, PASSWORD, "probe", "5821")
    # email-validator's reason quotes parts of the address; only the generic part stays.
    assert response.json() == {
        "detail": [{
            "loc": ["body", "email"],
            "msg": "value is not a valid email address",
            "type": "value_error",
        }]
    }


def test_register_password_too_long_keeps_our_own_message(client):
    response = client.post(
        "/api/auth/register", json={"email": EMAIL, "password": LONG_PASSWORD, "full_name": "X"}
    )
    assert_no_echo(response, LONG_PASSWORD, "echo-probe", EMAIL)
    assert response.json()["detail"][0]["msg"] == "Value error, Password must be at most 72 bytes"


@pytest.mark.parametrize(
    "body",
    [
        {"email": BAD_EMAIL, "password": PASSWORD},  # bad email
        {"email": EMAIL},  # missing password: the default echoes the whole body as input
        {"email": EMAIL, "password": [PASSWORD]},  # wrong type
        {"password": PASSWORD},  # missing email
    ],
)
def test_login_errors_echo_neither_password_nor_email(client, body):
    response = client.post("/api/auth/login", json=body)
    assert_no_echo(response, PASSWORD, EMAIL, BAD_EMAIL, "probe")


def test_broken_json_is_not_echoed(client):
    content = f'{{"email": "{EMAIL}", "password": "{PASSWORD}"'.encode()
    response = client.post(
        "/api/auth/login", content=content, headers={"content-type": "application/json"}
    )
    assert_no_echo(response, PASSWORD, EMAIL)


def test_nothing_is_logged(client, caplog):
    with caplog.at_level(logging.DEBUG):
        client.post("/api/auth/register", json={"email": EMAIL, "password": PASSWORD})
    assert PASSWORD not in caplog.text and EMAIL not in caplog.text


# --------------------------------------------------------------------------------------
# The auth page (frontend/pages/auth/auth.js describeError) still gets a usable message
# --------------------------------------------------------------------------------------

FIELD_LABELS = {"email": "Email", "password": "Password", "full_name": "Full name"}


def auth_page_message(detail) -> str:
    """A line-for-line port of auth.js describeError()."""
    if isinstance(detail, str):
        return detail
    first = detail[0]
    field = FIELD_LABELS.get(first["loc"][-1])
    msg = first["msg"].removeprefix("Value error, ")
    return f"{field}: {msg}" if field else msg


@pytest.mark.parametrize(
    ("body", "shown"),
    [
        ({"email": EMAIL, "password": PASSWORD, "full_name": "X"},
         "Password: String should have at least 8 characters"),
        ({"email": BAD_EMAIL, "password": PASSWORD + "-long-enough", "full_name": "X"},
         "Email: value is not a valid email address"),
        ({"email": EMAIL, "password": PASSWORD + "-long-enough", "full_name": "  "},
         "Full name: Full name is required"),
    ],
)
def test_auth_page_message_is_still_sensible(client, body, shown):
    response = client.post("/api/auth/register", json=body)
    assert auth_page_message(response.json()["detail"]) == shown


# --------------------------------------------------------------------------------------
# The sanitizer itself
# --------------------------------------------------------------------------------------


def test_ctx_keeps_only_numeric_limits():
    [error] = public_errors([{
        "loc": ("body", "x"), "msg": "m", "type": "t", "input": "v",
        "ctx": {"min_length": 8, "le": 100, "gt": 0.5, "ge": True, "reason": "r", "error": "e",
                "expected": "'a' or 'b'", "max_length": "9"},
    }])
    assert error["ctx"] == {"min_length": 8, "le": 100, "gt": 0.5}


def test_msg_containing_the_input_is_replaced():
    [error] = public_errors([{
        "loc": ("body", "x"), "msg": "Value error, secret-value is not allowed",
        "type": "value_error", "input": "secret-value",
    }])
    assert error["msg"] == GENERIC_MSG


def test_schema_values_in_msg_are_kept():
    msg = "Input should be 'oily' or 'dry'"
    [error] = public_errors([{
        "loc": ("body", "skin_type"), "msg": msg, "type": "literal_error", "input": "x",
        "ctx": {"expected": "'oily' or 'dry'"},
    }])
    assert error["msg"] == msg and "ctx" not in error


def test_long_loc_parts_are_truncated():
    [error] = public_errors([{"loc": ("body", "k" * 500), "msg": "Extra inputs are not permitted",
                              "type": "extra_forbidden", "input": 1}])
    assert len(error["loc"][1]) == 64


def test_questionnaire_endpoint_shape_is_unchanged(client):
    """Its own 422s stay {loc, msg, type}, with no ctx (see the questionnaire tests)."""
    response = client.post(
        "/api/services/questionnaire/score", json={"sensitivities_other": "x" * 501}
    )
    assert response.status_code == 422
    assert json.loads(response.text)["detail"] == [{
        "loc": ["body", "sensitivities_other"],
        "msg": "String should have at most 500 characters",
        "type": "string_too_long",
    }]
