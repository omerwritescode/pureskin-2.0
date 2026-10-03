"""The score_sources contract: where each Skin Profile value came from.

Stored in skin_profiles.score_sources (JSONB). Kept small and strict: unknown keys are
rejected and version strings are short identifiers, so raw answers, free text or
images can't be stored in it. Each entry holds everything needed to recompute its
final score (merge.reproduce_final).
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import skin_profile_config as cfg

Score = Annotated[int, Field(ge=cfg.SCORE_MIN, le=cfg.SCORE_MAX)]
VersionId = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[\w.+-]+$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScoreSourceVersions(_Strict):
    image_model: VersionId
    questionnaire_config: VersionId
    merge_config: VersionId


class ScoreSource(_Strict):
    method: Literal["image", "questionnaire", "blend"]
    image: Score | None
    questionnaire: Score | None
    # Effective weight of the image score: before any acne cap or floor,
    # final = round_half_up(w·image + (1 − w)·questionnaire).
    weight_image: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def method_matches_inputs(self):
        expected = {
            "image": (True, False, 1.0),
            "questionnaire": (False, True, 0.0),
            "blend": (True, True, None),
        }[self.method]
        has_image, has_questionnaire, weight = expected
        if (self.image is not None, self.questionnaire is not None) != (has_image, has_questionnaire):
            raise ValueError(f"method {self.method!r} doesn't match which inputs are present")
        if weight is not None and self.weight_image != weight:
            raise ValueError(f"method {self.method!r} needs weight_image {weight}")
        return self


class AcneScoreSource(ScoreSource):
    """Acne only: the cap / floor rule and whether it changed the score."""

    corroborated: bool  # the questionnaire estimate exists and is >= 61 (a property of the inputs)
    capped: bool  # the 60 cap actually lowered the final score
    floored: bool  # the 61 floor actually raised the final score

    @model_validator(mode="after")
    def flags_are_consistent(self):
        q = self.questionnaire
        if self.corroborated != (q is not None and q >= cfg.ACNE_CORROBORATION_MIN):
            raise ValueError("corroborated must be true exactly when questionnaire >= 61")
        if self.capped and self.corroborated:
            raise ValueError("a corroborated acne score is never capped")
        if self.floored and not self.corroborated:
            raise ValueError("only a corroborated acne score is floored")
        return self


class ScoreSourceMap(_Strict):
    acne_score: AcneScoreSource
    redness_score: ScoreSource
    wrinkle_score: ScoreSource
    pigmentation_score: ScoreSource
    pore_score: ScoreSource


class ScoreSources(_Strict):
    version: ScoreSourceVersions
    skin_type: Literal["questionnaire", "default"]
    is_sensitive: Literal["questionnaire"]
    scores: ScoreSourceMap

    def to_db(self) -> dict:
        """JSON for skin_profiles.score_sources."""
        return self.model_dump(mode="json")
