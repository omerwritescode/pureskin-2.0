import json

import pytest
from pydantic import ValidationError

from app.models.skin_profile import SCORE_COLUMNS
from app.services.skin_profile import ScoreSources, merge_score, reproduce_final

VERSION = {
    "image_model": "image-analysis-1.0.0+heuristic-1+skin-type-none",
    "questionnaire_config": "questionnaire-1.0.0",
    "merge_config": "merge-1.0.0",
}


def sources(acne=(95, 55), others=(40, None)) -> dict:
    entries = {}
    for name in SCORE_COLUMNS:
        image, q = acne if name == "acne_score" else others
        entries[name] = merge_score(name, image, q)[1]
    return {"version": VERSION, "skin_type": "questionnaire", "is_sensitive": "questionnaire",
            "scores": entries}


def test_merge_output_validates():
    ScoreSources.model_validate(sources())


@pytest.mark.parametrize("flag", ["corroborated", "capped", "floored"])
def test_acne_flags_are_required(flag):
    s = sources()
    del s["scores"]["acne_score"][flag]
    with pytest.raises(ValidationError):
        ScoreSources.model_validate(s)


@pytest.mark.parametrize("name", [n for n in SCORE_COLUMNS if n != "acne_score"])
@pytest.mark.parametrize("flag", ["corroborated", "capped", "floored"])
def test_other_scores_reject_the_acne_flags(name, flag):
    s = sources()
    s["scores"][name][flag] = False
    with pytest.raises(ValidationError):
        ScoreSources.model_validate(s)


@pytest.mark.parametrize(
    "acne_entry",
    [
        # corroborated must match the questionnaire estimate (>= 61)
        {"method": "blend", "image": 50, "questionnaire": 65, "weight_image": 0.25,
         "corroborated": False, "capped": False, "floored": False},
        {"method": "image", "image": 50, "questionnaire": None, "weight_image": 1.0,
         "corroborated": True, "capped": False, "floored": False},
        # a corroborated score is never capped; an uncorroborated one never floored
        {"method": "blend", "image": 50, "questionnaire": 65, "weight_image": 0.25,
         "corroborated": True, "capped": True, "floored": False},
        {"method": "blend", "image": 50, "questionnaire": 45, "weight_image": 0.25,
         "corroborated": False, "capped": False, "floored": True},
        # method must match which inputs are present
        {"method": "blend", "image": 50, "questionnaire": None, "weight_image": 0.25,
         "corroborated": False, "capped": False, "floored": False},
        {"method": "image", "image": 50, "questionnaire": None, "weight_image": 0.5,
         "corroborated": False, "capped": False, "floored": False},
    ],
)
def test_inconsistent_acne_entries_are_rejected(acne_entry):
    s = sources()
    s["scores"]["acne_score"] = acne_entry
    with pytest.raises(ValidationError):
        ScoreSources.model_validate(s)


@pytest.mark.parametrize(
    ("acne", "final"),
    [((5, 75), 65), ((49, 65), 61), ((95, 45), 55), ((1, 65), 61), ((95, 55), 60),
     ((80, None), 60), ((40, None), 40)],
)
def test_final_acne_score_reproduces_from_the_stored_json(acne, final):
    stored = json.loads(json.dumps(ScoreSources.model_validate(sources(acne=acne)).to_db()))
    assert reproduce_final("acne_score", stored["scores"]["acne_score"]) == final


def test_stored_json_has_flags_on_acne_only():
    stored = ScoreSources.model_validate(sources()).to_db()
    assert set(stored["scores"]["acne_score"]) == {
        "method", "image", "questionnaire", "weight_image", "corroborated", "capped", "floored",
    }
    for name in SCORE_COLUMNS[1:]:
        assert set(stored["scores"][name]) == {"method", "image", "questionnaire", "weight_image"}
