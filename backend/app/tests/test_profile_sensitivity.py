"""Step 7b-i: is_sensitive + score_sources on skin_profiles, through the profile API.

Covers the legacy mapping (the step 5 funnel still posts skin_type "sensitive"), the
new optional fields, strict score_sources validation, the DB CHECK, and the minimal
routine change (sensitivity read from is_sensitive).
"""

from types import SimpleNamespace

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.api.routine import build_requirements
from app.models import Base
from app.models.skin_profile import SKIN_TYPES
from app.services.questionnaire import questionnaire_config as qcfg
from app.services.skin_profile import merge_score, reproduce_final

SCORES = ("acne_score", "redness_score", "wrinkle_score", "pigmentation_score", "pore_score")
LOW_SCORES = dict.fromkeys(SCORES, 30)


def score_sources(acne=(20, 65), others=(30, None)) -> tuple[dict, dict]:
    """(score_sources, the scores it describes), built by the real merge."""
    scores, entries = {}, {}
    for name in SCORES:
        image, q = acne if name == "acne_score" else others
        scores[name], entries[name] = merge_score(name, image, q)
    sources = {
        "version": {
            "image_model": "image-analysis-1.0.0+heuristic-1+skin-type-none",
            "questionnaire_config": "questionnaire-1.0.0",
            "merge_config": "merge-1.0.0",
        },
        "skin_type": "questionnaire",
        "is_sensitive": "questionnaire",
        "scores": entries,
    }
    return sources, scores


def post(api, headers, **body):
    return api.post("/api/profile", json={**LOW_SCORES, **body}, headers=headers)


# --------------------------------------------------------------------------------------
# Profile API
# --------------------------------------------------------------------------------------


def test_payload_without_new_fields_still_works(api, auth_headers):
    created = post(api, auth_headers, skin_type="oily")
    assert created.status_code == 201
    assert created.json()["is_sensitive"] is False
    assert created.json()["score_sources"] is None
    fetched = api.get("/api/profile", headers=auth_headers).json()
    assert (fetched["skin_type"], fetched["is_sensitive"], fetched["score_sources"]) == (
        "oily", False, None,
    )


def test_legacy_sensitive_maps_to_default_type_plus_flag(api, auth_headers):
    """What a result saved in a browser before 7b-ii still sends at signup."""
    created = post(api, auth_headers, skin_type="sensitive")
    assert created.status_code == 201
    fetched = api.get("/api/profile", headers=auth_headers).json()
    assert fetched["skin_type"] == qcfg.DEFAULT_SKIN_TYPE == "normal"
    assert fetched["is_sensitive"] is True


def test_legacy_sensitive_wins_over_an_explicit_false(api, auth_headers):
    post(api, auth_headers, skin_type="sensitive", is_sensitive=False)
    assert api.get("/api/profile", headers=auth_headers).json()["is_sensitive"] is True


def test_new_fields_are_stored_and_returned(api, auth_headers):
    sources, scores = score_sources()
    created = post(api, auth_headers, skin_type="oily", is_sensitive=True, score_sources=sources,
                   **scores)
    assert created.status_code == 201, created.text
    fetched = api.get("/api/profile", headers=auth_headers).json()
    assert (fetched["skin_type"], fetched["is_sensitive"]) == ("oily", True)
    assert fetched["score_sources"] == sources
    # Acne-only fields aren't added to the other scores.
    assert "corroborated" not in fetched["score_sources"]["scores"]["redness_score"]


def test_stored_acne_score_reproduces_from_stored_sources(api, auth_headers):
    for acne in [(1, 65), (95, 55), (80, None), (5, 75)]:  # floored, capped, capped, plain
        sources, scores = score_sources(acne=acne)
        assert post(api, auth_headers, skin_type="oily", score_sources=sources,
                    **scores).status_code == 201
        fetched = api.get("/api/profile", headers=auth_headers).json()
        for name in SCORES:
            entry = fetched["score_sources"]["scores"][name]
            assert reproduce_final(name, entry) == fetched[name]


@pytest.mark.parametrize("name", SCORES)
def test_scores_must_match_their_sources(api, auth_headers, name):
    sources, scores = score_sources()
    tampered = {**scores, name: scores[name] % 100 + 1}  # any other valid value
    response = post(api, auth_headers, skin_type="oily", score_sources=sources, **tampered)
    assert response.status_code == 422


def test_older_merge_config_is_stored_without_the_reproduction_check(api, auth_headers):
    """A scan merged under an older config, saved at signup after an update, is accepted."""
    sources, scores = score_sources(acne=(95, 55))  # 60 under today's rules
    older = {**sources, "version": {**sources["version"], "merge_config": "merge-0.9.0"}}
    old_rules_scores = {**scores, "acne_score": 65}  # e.g. a config without the cap
    response = post(api, auth_headers, skin_type="oily", score_sources=older, **old_rules_scores)
    assert response.status_code == 201, response.text
    fetched = api.get("/api/profile", headers=auth_headers).json()
    assert fetched["acne_score"] == 65
    assert fetched["score_sources"]["version"]["merge_config"] == "merge-0.9.0"
    # The same mismatch under the current config is still rejected.
    assert post(api, auth_headers, skin_type="oily", score_sources=sources,
                **old_rules_scores).status_code == 422


def test_default_skin_type_source_is_allowed(api, auth_headers):
    sources, scores = score_sources()
    sources = {**sources, "skin_type": "default"}
    response = post(api, auth_headers, skin_type="normal", score_sources=sources, **scores)
    assert response.status_code == 201


@pytest.mark.parametrize("skin_type", ["not_sure", "Oily", "", None])
def test_invalid_skin_types_are_rejected(api, auth_headers, skin_type):
    assert post(api, auth_headers, skin_type=skin_type).status_code == 422


def _without(d: dict, key: str) -> dict:
    return {k: v for k, v in d.items() if k != key}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: {**s, "raw_answers": {"sensitivities_other": "lanolin"}},  # unknown key
        lambda s: {**s, "scores": _without(s["scores"], "pore_score")},  # missing score
        lambda s: {**s, "scores": {**s["scores"], "tan_score": s["scores"]["pore_score"]}},
        lambda s: {**s, "version": {**s["version"], "merge_config": "I react to lanolin"}},
        lambda s: {**s, "skin_type": "image"},  # skin type never comes from the image
        lambda s: {**s, "is_sensitive": "image"},
        lambda s: {**s, "scores": {**s["scores"], "acne_score": {
            **s["scores"]["acne_score"], "image": 101}}},
        lambda s: {**s, "scores": {**s["scores"], "acne_score": {
            **s["scores"]["acne_score"], "weight_image": 1.5}}},
        lambda s: {**s, "scores": {**s["scores"], "acne_score": {
            **s["scores"]["acne_score"], "note": "free text"}}},
        lambda s: {**s, "scores": {**s["scores"], "acne_score": _without(
            s["scores"]["acne_score"], "floored")}},  # acne flags are required
        lambda s: {**s, "scores": {**s["scores"], "redness_score": {
            **s["scores"]["redness_score"], "capped": False}}},  # acne only
    ],
)
def test_score_sources_are_validated_strictly(api, auth_headers, mutate):
    sources, scores = score_sources()
    response = post(api, auth_headers, skin_type="oily", score_sources=mutate(sources), **scores)
    assert response.status_code == 422


# --------------------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------------------


def test_db_check_rejects_sensitive_as_a_skin_type(migrated_db):
    with migrated_db.connect() as conn:
        user_id = conn.execute(
            text("INSERT INTO users (email, hashed_password) VALUES (:e, 'x') RETURNING id"),
            {"e": "check-test@example.com"},
        ).scalar_one()
        insert = text(
            "INSERT INTO skin_profiles (user_id, acne_score, redness_score, wrinkle_score, "
            "pigmentation_score, pore_score, skin_type) VALUES (:u, 30, 30, 30, 30, 30, :t)"
        )
        conn.execute(insert, {"u": user_id, "t": None})  # NULL stays allowed
        with pytest.raises(IntegrityError, match="ck_skin_profiles_skin_type_valid"):
            conn.execute(insert, {"u": user_id, "t": "sensitive"})
        conn.rollback()


def test_model_matches_migrated_schema(migrated_db):
    with migrated_db.connect() as conn:
        context = MigrationContext.configure(
            conn, opts={"compare_type": True, "compare_server_default": True}
        )
        assert compare_metadata(context, Base.metadata) == []


def test_skin_types_agree_between_db_and_questionnaire():
    assert SKIN_TYPES == qcfg.SKIN_TYPES
    assert qcfg.DEFAULT_SKIN_TYPE in SKIN_TYPES


# --------------------------------------------------------------------------------------
# Routine: sensitivity is honoured via is_sensitive
# --------------------------------------------------------------------------------------


def requirements(skin_type, is_sensitive, **scores):
    profile = SimpleNamespace(skin_type=skin_type, is_sensitive=is_sensitive, **LOW_SCORES)
    profile.__dict__.update(scores)
    return [(r.category, r.keywords, r.sessions) for r in build_requirements(profile)]


@pytest.mark.parametrize("skin_type", SKIN_TYPES)
@pytest.mark.parametrize("scores", [{}, dict.fromkeys(SCORES, 75)])
def test_is_sensitive_gives_the_old_sensitive_routine(skin_type, scores):
    assert requirements(skin_type, True, **scores) == requirements("sensitive", False, **scores)


@pytest.mark.parametrize("skin_type", SKIN_TYPES)
def test_not_sensitive_keeps_the_skin_types_routine(skin_type):
    assert requirements(skin_type, False) != requirements("sensitive", False)


def test_routine_reports_the_base_set_used(api, auth_headers):
    post(api, auth_headers, skin_type="oily", is_sensitive=True)
    routine = api.get("/api/routine", headers=auth_headers).json()
    assert (routine["skin_type"], routine["is_sensitive"]) == ("sensitive", True)
    post(api, auth_headers, skin_type="oily")
    routine = api.get("/api/routine", headers=auth_headers).json()
    assert (routine["skin_type"], routine["is_sensitive"]) == ("oily", False)
