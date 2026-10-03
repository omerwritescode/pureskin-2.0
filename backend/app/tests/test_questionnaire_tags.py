"""Questionnaire tags (7c-i c): the strict schema, the save path's drop policy, the round
trip from /api/scan/analyze to POST /api/profile, the routine flag, and deletion."""

import json

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.api import scan_analyze
from app.services.questionnaire import QuestionnaireTags
from app.services.questionnaire import questionnaire_config as qcfg

SCORES = ("acne_score", "redness_score", "wrinkle_score", "pigmentation_score", "pore_score")
LOW = dict.fromkeys(SCORES, 30)


def tags(**fields):
    return {"version": qcfg.CONFIG_VERSION, "actives_in_use": [], "products_in_use": [],
            "avoid": [], "stated_concern": None, **fields}


def save(api, headers, **body):
    return api.post("/api/profile", json={**LOW, "skin_type": "normal", **body}, headers=headers)


# --------------------------------------------------------------------------------------
# The schema: a fixed vocabulary, strict
# --------------------------------------------------------------------------------------


def test_a_full_tag_set_validates():
    QuestionnaireTags.model_validate(tags(
        actives_in_use=["prescription_retinoid", "salicylic acid"], products_in_use=["retinoid", "exfoliant"],
        avoid=["fragrance", "lanolin", "niacinamide"], stated_concern="acne",
    ))


@pytest.mark.parametrize("bad", [
    {**tags(), "raw_text": "I use tretinoin"},  # extra key
    {**tags(), "conditions": ["eczema"]},  # skin conditions are never stored
    tags(actives_in_use=["I use tretinoin from my dermatologist"]),  # raw text as a value
    tags(avoid=["eczema"]),
    tags(products_in_use=["toner"]),
    tags(actives_in_use=["retinol", "retinol"]),  # repeated
    tags(version="questionnaire-0.9.0"),  # unrecognised version
    tags(stated_concern="glow"),
    {k: v for k, v in tags().items() if k != "avoid"},  # missing key
    tags(avoid="fragrance"),  # wrong type
    tags(actives_in_use=[1]),
])
def test_invalid_tags_are_rejected(bad):
    with pytest.raises(ValidationError):
        QuestionnaireTags.model_validate(bad)


# --------------------------------------------------------------------------------------
# POST /api/profile: tags never fail a save, and a drop is never silent
# --------------------------------------------------------------------------------------


def test_valid_tags_are_stored(api, auth_headers, migrated_db):
    sent = tags(actives_in_use=["prescription_retinoid"], avoid=["fragrance"], stated_concern="acne")
    response = save(api, auth_headers, questionnaire_tags=sent)
    assert response.status_code == 201
    assert response.json()["questionnaire_tags_dropped"] is False
    with migrated_db.connect() as conn:
        stored = conn.execute(text("SELECT questionnaire_tags FROM skin_profiles WHERE id = :i"),
                              {"i": response.json()["id"]}).scalar_one()
    assert stored == sent
    assert api.get("/api/routine", headers=auth_headers).json()["current_products_considered"] is True


@pytest.mark.parametrize("body", [
    {},  # missing (e.g. a scan taken before 7c-i c)
    {"questionnaire_tags": None},
    {"questionnaire_tags": tags(version="questionnaire-0.9.0")},
    {"questionnaire_tags": {**tags(), "free_text": "SECRET-TEXT eczema"}},
    {"questionnaire_tags": tags(actives_in_use=["SECRET-TEXT tretinoin"])},
    {"questionnaire_tags": "SECRET-TEXT"},
    {"questionnaire_tags": ["SECRET-TEXT"]},
    {"questionnaire_tags": {"version": {"nested": "SECRET-TEXT"}}},
])
def test_missing_or_invalid_tags_save_the_profile_without_them(api, auth_headers, migrated_db, body):
    response = save(api, auth_headers, **body)
    assert response.status_code == 201
    payload = response.json()
    assert payload["questionnaire_tags_dropped"] is True
    assert "SECRET-TEXT" not in response.text  # never echoed
    assert "questionnaire_tags" not in payload  # the flag, never the contents
    with migrated_db.connect() as conn:
        is_null = conn.execute(text("SELECT questionnaire_tags IS NULL FROM skin_profiles WHERE id = :i"),
                               {"i": payload["id"]}).scalar_one()
    assert is_null  # SQL NULL, not a JSON null
    routine = api.get("/api/routine", headers=auth_headers).json()
    assert routine["current_products_considered"] is False


def test_empty_tags_are_not_a_drop(api, auth_headers):
    response = save(api, auth_headers, questionnaire_tags=tags())
    assert response.json()["questionnaire_tags_dropped"] is False
    assert api.get("/api/routine", headers=auth_headers).json()["current_products_considered"] is True


def test_invalid_scores_are_still_a_422_without_echo(api, auth_headers):
    response = save(api, auth_headers, acne_score=500, questionnaire_tags={"x": "SECRET-TEXT"})
    assert response.status_code == 422
    assert "SECRET-TEXT" not in response.text


def test_tags_are_never_logged(api, auth_headers, caplog):
    with caplog.at_level("DEBUG"):
        save(api, auth_headers, questionnaire_tags=tags(actives_in_use=["prescription_retinoid"]))
        save(api, auth_headers, questionnaire_tags={"bad": "SECRET-TEXT"})
    assert "prescription_retinoid" not in caplog.text and "SECRET-TEXT" not in caplog.text


# --------------------------------------------------------------------------------------
# Round trip: what /api/scan/analyze returns is what POST /api/profile accepts
# --------------------------------------------------------------------------------------


def fake_image(monkeypatch):
    monkeypatch.setattr(scan_analyze, "analyze_image", lambda _image: {
        **dict.fromkeys(SCORES, 40), "skin_type_prediction": None, "skin_type_confidence": None,
        "skin_type_labels_supported": [], "quality": {"ok": True, "issues": []},
        "model_version": "image-analysis-1.0.0+heuristic-1+skin-type-none",
    })


ANSWERS = {
    "oil_tzone": "oily", "oil_cheeks": "normal", "breakouts": "constantly", "primary_concern": "acne",
    "current_products": ["retinoid", "cleanser"],
    "current_products_other": "tretinoin from my dermatologist, and a vitamin C serum",
    "sensitivities": ["fragrance"], "sensitivities_other": "lanolin; I have eczema",
}


def test_analyze_tags_round_trip_into_the_profile(api, auth_headers, migrated_db, monkeypatch):
    fake_image(monkeypatch)
    result = api.post("/api/scan/analyze", json={"image": "data:,x", "answers": ANSWERS})
    assert result.status_code == 200
    returned = result.json()["questionnaire_tags"]
    QuestionnaireTags.model_validate(returned)  # the contract
    assert returned == tags(
        actives_in_use=["ascorbic acid", "prescription_retinoid"], products_in_use=["cleanser", "retinoid"],
        avoid=["fragrance", "lanolin"], stated_concern="acne",
    )
    body = {k: result.json()[k] for k in (*SCORES, "skin_type", "is_sensitive", "score_sources", "questionnaire_tags")}
    saved = api.post("/api/profile", json=body, headers=auth_headers)
    assert saved.status_code == 201 and saved.json()["questionnaire_tags_dropped"] is False
    with migrated_db.connect() as conn:
        row = conn.execute(text("SELECT questionnaire_tags::text FROM skin_profiles WHERE id = :i"),
                           {"i": saved.json()["id"]}).scalar_one()
    # Tags only: never the free text, the dermatologist, or the condition.
    assert json.loads(row) == returned
    for raw in ("dermatologist", "eczema", "tretinoin", "serum"):
        assert raw not in row


# --------------------------------------------------------------------------------------
# The database: an object or NULL, deleted with the user
# --------------------------------------------------------------------------------------


def _user_with_profile(conn, email, tags_json):
    user = conn.execute(text("INSERT INTO users (email, hashed_password) VALUES (:e, 'x') RETURNING id"),
                        {"e": email}).scalar_one()
    conn.execute(text(
        "INSERT INTO skin_profiles (user_id, acne_score, redness_score, wrinkle_score, pigmentation_score, "
        "pore_score, skin_type, questionnaire_tags) VALUES (:u, 30, 30, 30, 30, 30, 'normal', "
        "CAST(:t AS jsonb))"), {"u": user, "t": tags_json})
    return user


def test_the_column_holds_an_object_or_null(migrated_db):
    with migrated_db.connect() as conn:
        _user_with_profile(conn, "tags-object@example.com", json.dumps(tags()))
        with pytest.raises(IntegrityError, match="questionnaire_tags_object"):
            _user_with_profile(conn, "tags-list@example.com", json.dumps(["fragrance"]))
        conn.rollback()


def test_tags_are_deleted_with_the_user(migrated_db):
    with migrated_db.begin() as conn:
        user = _user_with_profile(conn, "tags-cascade@example.com",
                                  json.dumps(tags(actives_in_use=["prescription_retinoid"])))
    with migrated_db.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": user})
    with migrated_db.connect() as conn:
        left = conn.execute(text("SELECT count(*) FROM skin_profiles WHERE user_id = :u"), {"u": user}).scalar_one()
    assert left == 0
