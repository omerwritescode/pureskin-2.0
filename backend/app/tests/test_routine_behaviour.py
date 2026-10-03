"""Behaviour records for the rule-based routine (app/services/recommendation/).

First recorded on the step 6 code (before 7b-i), then re-recorded only after a reviewed
behaviour diff (7c-i b). The snapshots are what the code did, not a specification: a
change to them must be deliberate and reviewed.
"""

from types import SimpleNamespace

import pytest

from app.services.recommendation.rules import build_requirements
from app.services.skin_profile.skin_profile_config import HIGH_BAND_MIN
from app.tests.snapshot import check_snapshot

SCORES = ("acne_score", "redness_score", "wrinkle_score", "pigmentation_score", "pore_score")
SKIN_TYPES = ("oily", "dry", "combination", "normal", "sensitive", None, "unknown")


def stub_profile(skin_type, default=30, is_sensitive=False, **scores):
    values = {name: scores.get(name, default) for name in SCORES}
    return SimpleNamespace(skin_type=skin_type, is_sensitive=is_sensitive, **values)


def describe(requirements) -> list[dict]:
    return [
        {
            "category": r.category,
            "keywords": list(r.keywords),
            "sessions": list(r.sessions),
            "note": r.note,
        }
        for r in requirements
    ]


def requirement_cases() -> dict[str, SimpleNamespace]:
    cases = {}
    for skin_type in SKIN_TYPES:
        cases[f"{skin_type}/all_low"] = stub_profile(skin_type, default=30)
        cases[f"{skin_type}/all_high"] = stub_profile(skin_type, default=61)
    for score in SCORES:  # the > 60 trigger, either side of the boundary
        for value in (60, 61):
            cases[f"normal/{score}={value}"] = stub_profile("normal", **{score: value})
    for value in (40, 41):  # step 6's combination-only wrinkle > 40 rule (gone in 7c-i b)
        cases[f"combination/wrinkle_score={value}"] = stub_profile(
            "combination", wrinkle_score=value
        )
    return cases


def test_requirements_match_recorded_behaviour():
    actual = {name: describe(build_requirements(p)) for name, p in requirement_cases().items()}
    check_snapshot("routine_requirements", actual)


@pytest.mark.parametrize("score", SCORES)
def test_scores_trigger_at_the_high_band(score):
    """A score's steps are added from HIGH_BAND_MIN (61), the start of the High band."""
    at_60 = describe(build_requirements(stub_profile("normal", **{score: HIGH_BAND_MIN - 1})))
    at_61 = describe(build_requirements(stub_profile("normal", **{score: HIGH_BAND_MIN})))
    baseline = describe(build_requirements(stub_profile("normal")))
    assert at_60 == baseline
    assert len(at_61) > len(baseline)


# --------------------------------------------------------------------------------------
# End to end: POST /api/profile then GET /api/routine against a seeded throwaway DB
# --------------------------------------------------------------------------------------

ROUTINE_CASES = {
    "oily_low": {"skin_type": "oily", **dict.fromkeys(SCORES, 20)},
    "dry_high": {"skin_type": "dry", **dict.fromkeys(SCORES, 75)},
    "combination_wrinkle_45": {
        "skin_type": "combination", **dict.fromkeys(SCORES, 30), "wrinkle_score": 45,
    },
    "normal_acne_and_pigmentation": {
        "skin_type": "normal", **dict.fromkeys(SCORES, 30),
        "acne_score": 61, "pigmentation_score": 61,
    },
    "normal_pores": {"skin_type": "normal", **dict.fromkeys(SCORES, 30), "pore_score": 80},
    # The funnel's legacy answer: stored as normal + is_sensitive.
    "sensitive_redness": {"skin_type": "sensitive", **dict.fromkeys(SCORES, 30), "redness_score": 70},
    "sensitive_high": {"skin_type": "sensitive", **dict.fromkeys(SCORES, 75)},
}


def summarise(routine: dict) -> dict:
    def steps(session):
        return [
            [s["step"], s["product"]["name"], s["matched_keyword"], s["note"], s["caution"]]
            for s in session
        ]

    return {
        "skin_type": routine["skin_type"],
        "base_set": routine["base_set"],
        "is_sensitive": routine["is_sensitive"],
        "am": steps(routine["am_routine"]),
        "pm": steps(routine["pm_routine"]),
        "left_out": [[lo["product_name"], lo["sessions"], lo["reason"]] for lo in routine["left_out"]],
        "warnings": routine["warnings"],
        "message": routine["message"],
    }


def test_routine_endpoint_matches_recorded_behaviour(api, auth_headers):
    actual = {"no_profile": summarise(api.get("/api/routine", headers=auth_headers).json())}
    for name, body in ROUTINE_CASES.items():
        created = api.post("/api/profile", json=body, headers=auth_headers)
        assert created.status_code == 201, created.text
        response = api.get("/api/routine", headers=auth_headers)
        assert response.status_code == 200
        actual[name] = summarise(response.json())
    check_snapshot("routine_endpoint", actual)
