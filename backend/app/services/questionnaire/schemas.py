"""Input and output contracts of the questionnaire scorer.

Every field is optional: a skipped question is "no evidence", never a middle value.
Unknown keys and unknown values are rejected (HTTP 422 at the endpoints).
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import questionnaire_config as cfg


def _options(values) -> type:
    """A Literal of the accepted answers, taken from the config."""
    return Literal[tuple(values)]


def _list_of(values) -> type:
    return Annotated[list[_options(values)] | None, Field(max_length=cfg.MAX_LIST_ITEMS)]


FreeText = Annotated[str | None, Field(max_length=cfg.MAX_FREE_TEXT_CHARS)]


class QuestionnaireAnswers(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # --- The step 5 questionnaire (what the funnel sends today) ---
    skin_type: _options(cfg.LEGACY_SKIN_TYPE_LABELS) | None = None
    primary_concern: _options(cfg.PRIMARY_CONCERNS) | None = None
    sensitivities: _list_of(cfg.SENSITIVITY_CATEGORIES) = None
    sensitivities_other: FreeText = None
    current_products: _list_of(cfg.PRODUCT_TYPES) = None
    current_products_other: FreeText = None
    sleep: _options(cfg.SLEEP_OPTIONS) | None = None
    stress: _options(cfg.STRESS_OPTIONS) | None = None

    # --- Added for 7b-ii ---
    oil_tzone: _options(cfg.ZONE_OPTIONS) | None = None
    oil_cheeks: _options(cfg.ZONE_OPTIONS) | None = None
    reactivity: _options(cfg.REACTIVITY_OPTIONS) | None = None
    breakouts: _options(cfg.ESTIMATE_ANCHORS["breakouts"]) | None = None
    deep_bumps: _options(cfg.MODIFIER_POINTS["deep_bumps"]) | None = None
    flushing: _options(cfg.ESTIMATE_ANCHORS["flushing"]) | None = None
    fine_lines: _options(cfg.ESTIMATE_ANCHORS["fine_lines"]) | None = None
    dark_spots: _options(cfg.ESTIMATE_ANCHORS["dark_spots"]) | None = None
    pores: _options(cfg.ESTIMATE_ANCHORS["pores"]) | None = None


Estimate = Annotated[int, Field(ge=cfg.ESTIMATE_MIN, le=cfg.ESTIMATE_MAX)] | None


class Estimates(BaseModel):
    acne_score: Estimate
    redness_score: Estimate
    wrinkle_score: Estimate
    pigmentation_score: Estimate
    pore_score: Estimate


class QuestionnaireScore(BaseModel):
    """What score_questionnaire() returns. Contains tags only, never the free text."""

    config_version: str
    skin_type: _options(cfg.SKIN_TYPES)
    skin_type_basis: _options((cfg.BASIS_ZONES, cfg.BASIS_LABEL, cfg.BASIS_DEFAULT))
    is_sensitive: bool
    sensitivity_rules: list[Literal["S1", "S2", "S3", "S4"]]  # which rules fired
    estimates: Estimates  # null = the answers carry no evidence for that score
    stated_concern: _options(cfg.PRIMARY_CONCERNS) | None  # a goal, not a measurement
    concern_tags: list[str]  # concern words and skin conditions named in the free text
    actives_in_use: list[str]  # catalog ingredient names, plus prescription_retinoid
    avoid: list[str]  # categories, allergens and actives the user reacts to
    products_in_use: list[_options(cfg.PRODUCT_TYPES)]
    context_tags: list[str]  # lifestyle context (sleep, stress); never used in estimates
