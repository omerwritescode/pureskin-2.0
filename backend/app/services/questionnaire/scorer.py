"""score_questionnaire(answers) -> skin type, sensitivity, per-score estimates and tags.

Pure and deterministic: no I/O, no model, no logging. Every rule and number lives in
questionnaire_config.py; README.md explains them.
"""

from collections.abc import Mapping

from . import questionnaire_config as cfg
from .lexicon import extract_products, extract_sensitivities
from .schemas import QuestionnaireAnswers


def score_questionnaire(answers: Mapping | QuestionnaireAnswers) -> dict:
    """Score questionnaire answers (the QuestionnaireScore contract, as a dict).

    Raises pydantic.ValidationError for malformed answers, unknown keys or unknown
    values. Missing answers are "no evidence": estimates without evidence are None.
    """
    a = (
        answers
        if isinstance(answers, QuestionnaireAnswers)
        else QuestionnaireAnswers.model_validate(answers)
    )
    sensitivities_text = extract_sensitivities(a.sensitivities_other)
    products_text = extract_products(a.current_products_other)

    skin_type, basis = _skin_type(a)
    rules = _sensitivity_rules(a, set(a.sensitivities or ()) | sensitivities_text.signals)
    return {
        "config_version": cfg.CONFIG_VERSION,
        "skin_type": skin_type,
        "skin_type_basis": basis,
        "is_sensitive": bool(rules),
        "sensitivity_rules": rules,
        "estimates": {score: _estimate(a, score) for score in cfg.SCORE_QUESTIONS},
        "stated_concern": a.primary_concern,
        "concern_tags": sorted(
            sensitivities_text.concerns | sensitivities_text.conditions | products_text.concerns
        ),
        "actives_in_use": sorted(products_text.actives),
        "avoid": sorted(set(a.sensitivities or ()) | sensitivities_text.avoid),
        "products_in_use": sorted(set(a.current_products or ())),
        "context_tags": sorted(
            tag
            for (question, answer), tag in cfg.CONTEXT_TAGS.items()
            if getattr(a, question) == answer
        ),
    }


def _skin_type(a: QuestionnaireAnswers) -> tuple[str, str]:
    zones = cfg.ZONE_SKIN_TYPES.get((a.oil_tzone, a.oil_cheeks))  # T1
    if zones is not None:
        return zones, cfg.BASIS_ZONES
    label = cfg.LABEL_SKIN_TYPES.get(a.skin_type)  # T2
    if label is not None:
        return label, cfg.BASIS_LABEL
    return cfg.DEFAULT_SKIN_TYPE, cfg.BASIS_DEFAULT  # T3


def _sensitivity_rules(a: QuestionnaireAnswers, signals: set[str]) -> list[str]:
    fired = {
        "S1": a.skin_type == cfg.SENSITIVE_LABEL,
        "S2": a.reactivity in cfg.REACTIVITY_SENSITIVE,
        "S3": a.reactivity in cfg.REACTIVITY_SENSITIVE_WITH_SIGNAL
        and len(signals) >= cfg.S3_MIN_SIGNALS,
        "S4": len(signals) >= cfg.S4_MIN_SIGNALS,
    }
    return [rule for rule, hit in fired.items() if hit]


def _estimate(a: QuestionnaireAnswers, score: str) -> int | None:
    question, modifiers = cfg.SCORE_QUESTIONS[score]
    answer = getattr(a, question)
    base = None if answer is None else cfg.ESTIMATE_ANCHORS[question][answer]
    if base is None:  # unanswered or "not sure": no evidence
        return None
    total = base + sum(
        cfg.MODIFIER_POINTS[m][getattr(a, m)] for m in modifiers if getattr(a, m) is not None
    )
    return max(cfg.ESTIMATE_MIN, min(cfg.ESTIMATE_MAX, round(total)))
