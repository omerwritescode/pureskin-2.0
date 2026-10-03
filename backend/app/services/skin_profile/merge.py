"""Merge one image score and one questionnaire estimate into a final 1-100 score.

Pure and deterministic. Every number lives in skin_profile_config.py; README.md
explains the rules. Each merged score comes with a score_sources entry from which
reproduce_final() recomputes it exactly.
"""

import math

from . import skin_profile_config as cfg


def band(score: int) -> str:
    """Low / Moderate / High for a 1-100 score (the shared cutoffs)."""
    for name, low, high in cfg.SCORE_BANDS:
        if low <= score <= high:
            return name
    raise ValueError(f"score {score} is outside {cfg.SCORE_MIN}-{cfg.SCORE_MAX}")


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def blend(image: int | None, questionnaire: int | None, weight_image: float) -> int:
    """round(w·image + (1 − w)·questionnaire), half up, as an int in 1-100.

    With only one input present, that input. The single formula both merge_score()
    and reproduce_final() use, so the stored fields reproduce a score exactly.
    """
    if questionnaire is None:
        return image
    if image is None:
        return questionnaire
    value = math.floor(weight_image * image + (1 - weight_image) * questionnaire + 0.5)
    return int(_clamp(value, cfg.SCORE_MIN, cfg.SCORE_MAX))


def merge_score(name: str, image: int, questionnaire: int | None) -> tuple[int, dict]:
    """(final score, its score_sources entry)."""
    if name == cfg.ACNE_SCORE:
        return _merge_acne(image, questionnaire)
    if name not in cfg.IMAGE_PRIMARY_SCORES:
        raise ValueError(f"unknown score {name!r}")
    if questionnaire is None:
        return image, _entry("image", image, None, 1.0)

    gap = questionnaire - image
    shift = _clamp(cfg.QUESTIONNAIRE_PULL * gap, -cfg.MAX_QUESTIONNAIRE_SHIFT, cfg.MAX_QUESTIONNAIRE_SHIFT)
    weight = 1 - (cfg.QUESTIONNAIRE_PULL if gap == 0 else shift / gap)
    weight = round(weight, cfg.WEIGHT_DECIMALS)
    return blend(image, questionnaire, weight), _entry("blend", image, questionnaire, weight)


def _merge_acne(image: int, questionnaire: int | None) -> tuple[int, dict]:
    if questionnaire is None:
        method, weight, value = "image", 1.0, image
    else:
        gap = image - questionnaire
        shift = _clamp(cfg.ACNE_IMAGE_PULL * gap, -cfg.ACNE_MAX_IMAGE_SHIFT, cfg.ACNE_MAX_IMAGE_SHIFT)
        weight = round(cfg.ACNE_IMAGE_PULL if gap == 0 else shift / gap, cfg.WEIGHT_DECIMALS)
        method, value = "blend", blend(image, questionnaire, weight)

    corroborated = questionnaire is not None and questionnaire >= cfg.ACNE_CORROBORATION_MIN
    if corroborated:
        final = max(value, cfg.ACNE_CORROBORATED_FLOOR)
    else:
        final = min(value, cfg.ACNE_UNCORROBORATED_CAP)
    entry = _entry(method, image, questionnaire, weight)
    entry.update(corroborated=corroborated, capped=final < value, floored=final > value)
    return final, entry


def _entry(method: str, image: int | None, questionnaire: int | None, weight: float) -> dict:
    return {"method": method, "image": image, "questionnaire": questionnaire, "weight_image": weight}


def reproduce_final(name: str, entry: dict) -> int:
    """Recompute a final score from its stored score_sources entry alone."""
    value = blend(entry["image"], entry["questionnaire"], entry["weight_image"])
    if name == cfg.ACNE_SCORE:
        if entry["capped"]:
            return min(value, cfg.ACNE_UNCORROBORATED_CAP)
        if entry["floored"]:
            return max(value, cfg.ACNE_CORROBORATED_FLOOR)
    return value
