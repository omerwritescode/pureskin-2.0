"""Merged profiles through the step 6 routine: /api/scan/analyze -> /api/profile -> /api/routine.

The image analyzer is replaced by fixed scores so each case is exact. The routine is the
7c-i (b) rule set (app/services/recommendation/).
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
        saved = api.post("/api/profile", json=dashboard_body(result.json()), headers=auth_headers)
        assert saved.status_code == 201, saved.text
        routine = api.get("/api/routine", headers=auth_headers).json()
        return result.json(), routine

    return run


def dashboard_body(result: dict) -> dict:
    """What frontend/pages/app/dashboard.js posts at first login: no image, no display-only fields."""
    keys = (*SCORES, "skin_type", "is_sensitive", "score_sources")
    return {key: result[key] for key in keys}


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


def test_oily_sensitive_profile_keeps_the_oily_steps(scan_to_routine):
    answers = {"oil_tzone": "oily", "oil_cheeks": "oily", "reactivity": "often"}
    profile, routine = scan_to_routine(answers, redness_score=70)
    assert (profile["skin_type"], profile["is_sensitive"]) == ("oily", True)
    assert (routine["skin_type"], routine["base_set"], routine["is_sensitive"]) == ("oily", "oily", True)
    found = keywords(routine)
    assert {("am_routine", "foaming"), ("am_routine", "lightweight")} <= found  # the oily steps
    assert ("am_routine", "mineral") in found  # sensitive: mineral sunscreen first
    assert ("am_routine", "azelaic acid") in found  # redness 70 is High


def test_todays_funnel_answers_keep_the_self_reported_type(scan_to_routine):
    profile, routine = scan_to_routine(TODAYS_ANSWERS, pigmentation_score=66)
    assert routine["skin_type"] == "combination"
    assert profile["pigmentation_score"] == 66  # no questionnaire evidence: image only
    assert ("pm_routine", "tranexamic acid") in keywords(routine)
    # The only arbutin serum lists lactic acid (an AHA), and AHAs are evening-only, so the
    # morning step is skipped with a visible reason (a gap of the fixture catalog the test
    # database holds). It isn't
    # in the evening routine either, so the reason says "left out".
    (arbutin,) = [lo for lo in routine["left_out"] if lo["product_name"] == "Alpha Arbutin 2% + HA Serum"]
    assert arbutin["sessions"] == ["am"]
    assert arbutin["reason"] == (
        "Left out because it contains lactic acid (an AHA), and AHAs are not used in the morning routine."
    )


def test_a_few_spots_keep_pigmentation_moderate(scan_to_routine):
    """Image pigmentation 66 with "a few" dark spots merges to 55: no pigmentation steps."""
    profile, routine = scan_to_routine({**TODAYS_ANSWERS, "dark_spots": "a_few"}, pigmentation_score=66)
    assert profile["pigmentation_score"] == 55
    found = {keyword for _, keyword in keywords(routine)}
    assert not {"alpha arbutin", "tranexamic acid"} & found
    assert not any(lo["product_name"] == "Alpha Arbutin 2% + HA Serum" for lo in routine["left_out"])


# --------------------------------------------------------------------------------------
# The 7b-ii questionnaire, as frontend/pages/scan/questionnaire/questionnaire.js sends it
# ("not_sure" answers are left out; unticked checkbox groups are empty lists)
# --------------------------------------------------------------------------------------

NEW_UI_ANSWERS = {
    "oil_tzone": "oily", "oil_cheeks": "normal", "breakouts": "occasionally", "deep_bumps": "no",
    "flushing": "rarely", "dark_spots": "none", "fine_lines": "none", "pores": "on_nose",
    "primary_concern": "acne", "reactivity": "never", "sensitivities": [],
    "sensitivities_other": "", "current_products": [], "current_products_other": "",
    "sleep": "6_to_8", "stress": "medium",
}


def test_breakouts_constantly_reaches_high_and_adds_acne_steps(scan_to_routine):
    profile, routine = scan_to_routine({**NEW_UI_ANSWERS, "breakouts": "constantly"}, acne_score=10)
    assert profile["acne_score"] >= 61
    assert (profile["skin_type"], routine["skin_type"]) == ("combination", "combination")
    assert ACNE_STEPS <= keywords(routine)


def test_rarely_breakouts_with_high_image_acne_adds_no_acne_steps(scan_to_routine):
    profile, routine = scan_to_routine({**NEW_UI_ANSWERS, "breakouts": "rarely_or_never"},
                                       acne_score=95)
    assert profile["acne_score"] <= 60
    assert not ACNE_STEPS & keywords(routine)


def test_reactive_answers_give_a_sensitive_profile(scan_to_routine):
    profile, routine = scan_to_routine({**NEW_UI_ANSWERS, "reactivity": "often"})
    assert profile["is_sensitive"] is True
    assert (routine["skin_type"], routine["is_sensitive"]) == ("combination", True)


def test_skipped_skin_feel_questions_are_stored_as_an_assumed_type(api, auth_headers, scan_to_routine):
    answers = {k: v for k, v in NEW_UI_ANSWERS.items() if k not in ("oil_tzone", "oil_cheeks")}
    profile, _ = scan_to_routine(answers)
    assert profile["skin_type"] == "normal"
    saved = api.get("/api/profile", headers=auth_headers).json()
    assert saved["score_sources"]["skin_type"] == "default"  # the profile page shows "(assumed)"


def test_the_saved_profile_never_holds_the_image(api, auth_headers, scan_to_routine):
    scan_to_routine(NEW_UI_ANSWERS)
    saved = api.get("/api/profile", headers=auth_headers).json()
    assert "image" not in saved and saved.get("raw_image_path") is None
    assert "data:" not in str(saved)
