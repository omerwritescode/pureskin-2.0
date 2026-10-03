"""Merged profiles through the step 6 routine: /api/scan/analyze -> /api/profile -> /api/routine.

The image analyzer is replaced by fixed scores so each case is exact. The routine
itself is the unchanged step 6 code (plus the 7b-i is_sensitive compatibility).
"""

import pytest

from app.api import scan_analyze

TODAYS_ANSWERS = {
    "skin_type": "combination", "primary_concern": "acne", "sensitivities": [],
    "sensitivities_other": "", "current_products": [], "current_products_other": "",
    "sleep": "6_to_8", "stress": "medium",
}
SCORES = ("acne_score", "redness_score", "wrinkle_score", "pigmentation_score", "pore_score")


@pytest.fixture
def scan_to_routine(api, auth_headers, monkeypatch):
    def run(answers: dict, **image_scores):
        image = {**dict.fromkeys(SCORES, 40), **image_scores}
        monkeypatch.setattr(scan_analyze, "analyze_image", lambda _image: {
            **image, "skin_type_prediction": None, "skin_type_confidence": None,
            "skin_type_labels_supported": [], "quality": {"ok": True, "issues": []},
            "model_version": "image-analysis-1.0.0+heuristic-1+skin-type-none",
        })
        result = api.post("/api/scan/analyze", json={"image": "data:,x", "answers": answers})
        assert result.status_code == 200, result.text
        saved = api.post("/api/profile", json=result.json(), headers=auth_headers)
        assert saved.status_code == 201, saved.text
        routine = api.get("/api/routine", headers=auth_headers).json()
        return result.json(), routine

    return run


def keywords(routine: dict) -> set[tuple[str, str]]:
    return {
        (session, step["matched_keyword"])
        for session in ("am_routine", "pm_routine")
        for step in routine[session]
        if step["matched_keyword"]
    }


ACNE_STEPS = {("am_routine", "salicylic acid"), ("pm_routine", "benzoyl peroxide")}


def test_high_image_acne_without_corroboration_adds_no_acne_steps(scan_to_routine):
    profile, routine = scan_to_routine(TODAYS_ANSWERS, acne_score=92)
    assert profile["acne_score"] == 60
    assert not ACNE_STEPS & keywords(routine)
    assert routine["skin_type"] == "combination"


def test_uncorroborated_self_report_adds_no_acne_steps(scan_to_routine):
    profile, routine = scan_to_routine({"breakouts": "most_weeks", "deep_bumps": "sometimes"},
                                       acne_score=95)
    assert profile["acne_score"] == 60  # 65 before the cap
    assert not ACNE_STEPS & keywords(routine)


def test_corroborated_acne_adds_acne_steps_even_with_a_low_image_score(scan_to_routine):
    profile, routine = scan_to_routine({**TODAYS_ANSWERS, "breakouts": "most_weeks",
                                        "deep_bumps": "often"}, acne_score=1)
    assert profile["acne_score"] == 61  # floored
    assert ACNE_STEPS <= keywords(routine)


def test_sensitive_profile_gets_the_sensitive_routine(scan_to_routine):
    answers = {"oil_tzone": "oily", "oil_cheeks": "oily", "reactivity": "often"}
    profile, routine = scan_to_routine(answers, redness_score=70)
    assert (profile["skin_type"], profile["is_sensitive"]) == ("oily", True)
    assert (routine["skin_type"], routine["is_sensitive"]) == ("sensitive", True)
    found = keywords(routine)
    assert {("am_routine", "fragrance-free"), ("am_routine", "mineral")} <= found
    assert ("am_routine", "azelaic acid") in found  # redness 70 > 60
    assert ("am_routine", "oil-free") not in found  # the oily set is replaced (7c: combine)


def test_todays_funnel_answers_keep_the_self_reported_type(scan_to_routine):
    profile, routine = scan_to_routine(TODAYS_ANSWERS, pigmentation_score=66)
    assert routine["skin_type"] == "combination"
    assert profile["pigmentation_score"] == 66  # no questionnaire evidence: image only
    assert ("am_routine", "alpha arbutin") in keywords(routine)
