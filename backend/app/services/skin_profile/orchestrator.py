"""build_skin_profile(): Image Analysis result + questionnaire result -> one Skin Profile.

Pure: the caller runs the two services (see app/api/scan_analyze.py). Nothing is
stored here, and no raw answers, free text or images go into the result.
"""

from app.models.skin_profile import SCORE_COLUMNS

from . import skin_profile_config as cfg
from .merge import merge_score
from .schemas import ScoreSources


def build_skin_profile(image_result: dict, questionnaire_result: dict) -> dict:
    """Merge the two services' outputs.

    image_result: analyze_image()'s contract. Its skin_type_prediction is ignored on
    purpose: skin type and sensitivity come from the questionnaire only.
    questionnaire_result: score_questionnaire()'s contract.
    """
    scores, entries = {}, {}
    for name in SCORE_COLUMNS:
        scores[name], entries[name] = merge_score(
            name, image_result[name], questionnaire_result["estimates"][name]
        )

    default_type = questionnaire_result["skin_type_basis"] == "default"
    score_sources = ScoreSources.model_validate({
        "version": {
            "image_model": image_result["model_version"],
            "questionnaire_config": questionnaire_result["config_version"],
            "merge_config": cfg.MERGE_CONFIG_VERSION,
        },
        "skin_type": "default" if default_type else "questionnaire",
        "is_sensitive": "questionnaire",
        "scores": entries,
    }).to_db()

    return {
        **scores,
        "skin_type": questionnaire_result["skin_type"],
        "is_sensitive": questionnaire_result["is_sensitive"],
        "score_sources": score_sources,
        "sources": summarise(score_sources),
        "quality": image_result["quality"],  # soft warnings only: hard ones never get here
    }


def summarise(score_sources: dict) -> dict[str, str]:
    """A short, human-readable source per field, e.g. for the Skin Report page."""
    summary = {
        "skin_type": (
            "default (no oil/dry answer)"
            if score_sources["skin_type"] == "default"
            else "questionnaire"
        ),
        "is_sensitive": "questionnaire",
    }
    for name, entry in score_sources["scores"].items():
        if name == cfg.ACNE_SCORE:
            text = "questionnaire + image" if entry["method"] == "blend" else "image only"
            if entry["capped"]:
                text += f", capped at {cfg.ACNE_UNCORROBORATED_CAP} (not corroborated)"
            elif entry["floored"]:
                text += f", raised to {cfg.ACNE_CORROBORATED_FLOOR} (High self-report)"
            elif not entry["corroborated"]:
                text += f", at most {cfg.ACNE_UNCORROBORATED_CAP} without corroboration"
        else:
            text = "image + questionnaire" if entry["method"] == "blend" else "image only"
        summary[name] = text
    return summary
