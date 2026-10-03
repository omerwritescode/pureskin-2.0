"""POST /api/scan/analyze: selfie + questionnaire answers -> one merged Skin Profile.

No auth (the funnel runs before signup) and no database writes: the photo is decoded,
scored and discarded in memory, and nothing is logged. The visitor saves the result
with POST /api/profile after signing up. The funnel switches to this endpoint in 7b-ii;
until then it keeps using /api/scan/mock-analyze, which is untouched.

| Status | Body |
|---|---|
| 200 | the five scores, skin_type, is_sensitive, score_sources, sources, quality |
| 422 | {"detail": [{loc, msg, type}]}: malformed body or answers (input never echoed) |
| 422 | {"quality": {"ok": false, "issues": [...]}}: photo unusable (as the image endpoint) |
| 413 | {"detail": "..."}: body over the image endpoint's limit |
| 503 | {"detail": "..."}: face model missing. No fallback scores, ever. |
"""

import json
from typing import Literal

from fastapi import APIRouter, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.api.image_analysis import TOO_LARGE, ImageRejectedResponse, Quality, Score
from app.api.request_body import (
    PayloadTooLarge,
    invalid_json_response,
    read_body,
    too_large_response,
    validation_error_response,
)
from app.models.skin_profile import SKIN_TYPES
from app.services.image_analysis import ImageRejected, ModelUnavailable, analyze_image
from app.services.image_analysis.scoring_config import (
    MAX_DRAINED_BYTES,
    MAX_REQUEST_BYTES,
)
from app.services.questionnaire import QuestionnaireAnswers, score_questionnaire
from app.services.skin_profile import ScoreSources, build_skin_profile

router = APIRouter(prefix="/api/scan", tags=["scan"])

NOT_JSON = 'Send JSON of the form {"image": "<base64 JPEG or data URL>", "answers": {...}}.'


class AnalyzeRequest(BaseModel):
    # extra="forbid": no lighting-gate bypass or any other switch can be passed in.
    model_config = ConfigDict(extra="forbid")

    image: str = Field(min_length=1, description="Base64 JPEG/PNG, bare or as a data URL")
    answers: QuestionnaireAnswers


class AnalyzeResponse(BaseModel):
    acne_score: Score
    redness_score: Score
    wrinkle_score: Score
    pigmentation_score: Score
    pore_score: Score
    skin_type: Literal[SKIN_TYPES]  # from the questionnaire only, never the image
    is_sensitive: bool
    score_sources: ScoreSources
    sources: dict[str, str]
    quality: Quality  # soft warnings only


@router.post(
    "/analyze",
    response_model=AnalyzeResponse,
    summary="Selfie + questionnaire -> one merged Skin Profile (nothing stored)",
    responses={
        413: {"description": TOO_LARGE},
        422: {
            "model": ImageRejectedResponse,
            "description": 'Photo unusable ({"quality": ...}), or malformed body / answers '
                           '({"detail": [...]}, input never echoed).',
        },
        503: {"description": "Face landmark model not downloaded. No fallback scores."},
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": AnalyzeRequest.model_json_schema()}},
        }
    },
)
async def analyze(request: Request):
    # Parsed by hand (as the image endpoint does) so an oversized upload is refused
    # before it is buffered, and so no error can echo the photo or the free text.
    try:
        body = await read_body(request, MAX_REQUEST_BYTES, MAX_DRAINED_BYTES)
    except PayloadTooLarge:
        return too_large_response(TOO_LARGE)
    try:
        payload = json.loads(body)
    except ValueError:
        return invalid_json_response(NOT_JSON)
    try:
        req = AnalyzeRequest.model_validate(payload)
    except ValidationError as exc:
        return validation_error_response(exc)

    questionnaire = score_questionnaire(req.answers)  # cheap and pure: do it first
    try:
        # CPU-bound (~0.1-0.3 s); run it off the event loop.
        image = await run_in_threadpool(analyze_image, req.image)
    except ImageRejected as exc:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"quality": {"ok": False, "issues": exc.issues}},
        )
    except ModelUnavailable as exc:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(exc)}
        )
    return build_skin_profile(image, questionnaire)
