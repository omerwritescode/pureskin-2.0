# ---------------------------------------------------------------------------
# TEMPORARY MOCK — replace in roadmap step 7 (docs/spec.md §8).
#
# POST /api/scan/mock-analyze returns fake-but-plausible Skin Profile scores so the
# onboarding funnel (/scan/ -> /scan/questionnaire/ -> /scan/report/) can be built and
# tested end to end. It will be replaced by the real Image Analysis and
# Questionnaire/NLP services, whose outputs are merged into one Skin Profile.
#
# Stateless by design: the visitor hasn't signed up, so there is no user_id and
# nothing is written to the database. The image is accepted but never inspected.
# ---------------------------------------------------------------------------

import random
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/scan", tags=["scan"])

SkinType = Literal["oily", "dry", "combination", "normal", "sensitive"]
Concern = Literal["acne", "redness", "wrinkles", "pigmentation", "pores", "none"]

# The frontend downsizes photos to ~720px JPEG (well under 1 MB of base64);
# this cap just stops absurd payloads.
MAX_IMAGE_CHARS = 5_000_000


class QuestionnaireAnswers(BaseModel):
    skin_type: SkinType | Literal["not_sure"]
    primary_concern: Concern
    sensitivities: list[str] = Field(default_factory=list, max_length=20)
    sensitivities_other: str = Field(default="", max_length=500)
    current_products: list[str] = Field(default_factory=list, max_length=20)
    current_products_other: str = Field(default="", max_length=500)
    sleep: Literal["under_6", "6_to_8", "over_8"]
    stress: Literal["low", "medium", "high"]


class MockAnalyzeRequest(BaseModel):
    image: str = Field(min_length=1, max_length=MAX_IMAGE_CHARS)  # base64 data URL
    answers: QuestionnaireAnswers


class MockAnalyzeResponse(BaseModel):
    # Same shape and 1–100 range as the skin_profiles score columns.
    acne_score: int = Field(ge=1, le=100)
    redness_score: int = Field(ge=1, le=100)
    wrinkle_score: int = Field(ge=1, le=100)
    pigmentation_score: int = Field(ge=1, le=100)
    pore_score: int = Field(ge=1, le=100)
    skin_type: SkinType


CONCERN_TO_SCORE = {
    "acne": "acne_score",
    "redness": "redness_score",
    "wrinkles": "wrinkle_score",
    "pigmentation": "pigmentation_score",
    "pores": "pore_score",
}


@router.post("/mock-analyze", response_model=MockAnalyzeResponse)
def mock_analyze(body: MockAnalyzeRequest) -> MockAnalyzeResponse:
    scores = {field: random.randint(1, 100) for field in CONCERN_TO_SCORE.values()}

    # Nudge the result toward what the visitor told us so the report feels plausible.
    concern_field = CONCERN_TO_SCORE.get(body.answers.primary_concern)
    if concern_field:
        scores[concern_field] = random.randint(55, 100)

    skin_type = body.answers.skin_type
    if skin_type == "not_sure":
        skin_type = random.choice(["oily", "dry", "combination", "normal", "sensitive"])

    return MockAnalyzeResponse(**scores, skin_type=skin_type)
