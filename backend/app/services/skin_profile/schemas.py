"""The score_sources contract: where each Skin Profile value came from.

Stored in skin_profiles.score_sources (JSONB). Kept small and strict: unknown keys are
rejected and version strings are short identifiers, so raw answers, free text or
images can't be stored in it.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.skin_profile import SCORE_COLUMNS

Score = Annotated[int, Field(ge=1, le=100)]
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
    # Effective weight of the image score: final ≈ w·image + (1 − w)·questionnaire.
    weight_image: float = Field(ge=0, le=1)
    # Acne only: whether the questionnaire corroborated a High score, and whether the
    # cap (no corroboration -> at most 60) lowered the value.
    corroborated: bool | None = None
    capped: bool | None = None


class ScoreSources(_Strict):
    version: ScoreSourceVersions
    skin_type: Literal["questionnaire", "default"]
    is_sensitive: Literal["questionnaire"]
    scores: dict[Literal[SCORE_COLUMNS], ScoreSource]

    @model_validator(mode="after")
    def every_score_has_a_source(self):
        missing = set(SCORE_COLUMNS) - set(self.scores)
        if missing:
            raise ValueError(f"scores is missing {', '.join(sorted(missing))}")
        return self

    def to_db(self) -> dict:
        """JSON for skin_profiles.score_sources; acne-only fields are left out elsewhere."""
        return self.model_dump(mode="json", exclude_unset=True)
