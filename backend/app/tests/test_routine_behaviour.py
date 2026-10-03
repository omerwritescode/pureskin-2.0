"""Behaviour records for the step 6 rule-based routine (app/services/recommendation/).

Recorded on the unchanged step 6 code before 7b-i touched routine.py, so they show
that the 7b-i compatibility change (sensitivity read from is_sensitive) left the
routine's output alone. The snapshots are what the code did, not a specification:
7c is expected to change them deliberately.
"""

from types import SimpleNamespace

import pytest

from app.services.recommendation.rules import build_requirements
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
    for value in (40, 41):  # combination's separate wrinkle > 40 retinol rule
        cases[f"combination/wrinkle_score={value}"] = stub_profile(
            "combination", wrinkle_score=value
        )
    return cases


def test_requirements_match_recorded_behaviour():
    actual = {name: describe(build_requirements(p)) for name, p in requirement_cases().items()}
    check_snapshot("routine_requirements", actual)


@pytest.mark.parametrize("score", SCORES)
def test_scores_trigger_strictly_above_60(score):
    """The step 6 trigger is score > 60, i.e. exactly the High band (61-100)."""
    at_60 = describe(build_requirements(stub_profile("normal", **{score: 60})))
    at_61 = describe(build_requirements(stub_profile("normal", **{score: 61})))
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
    # The funnel's legacy answer. Its routine must stay the same across 7b-i.
    "sensitive_redness": {"skin_type": "sensitive", **dict.fromkeys(SCORES, 30), "redness_score": 70},
    "sensitive_high": {"skin_type": "sensitive", **dict.fromkeys(SCORES, 75)},
}


def summarise(routine: dict) -> dict:
    def steps(session):
        return [
            [s["step"], s["product"]["name"], s["matched_keyword"], s["note"]] for s in session
        ]

    return {
        "skin_type": routine["skin_type"],
        "am": steps(routine["am_routine"]),
        "pm": steps(routine["pm_routine"]),
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
