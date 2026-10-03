"""POST /api/services/questionnaire/score: the Questionnaire/NLP service, exposed on its own.

No auth, because the onboarding funnel runs before signup. Stateless: nothing is
stored or logged, and the free text never comes back, not even in an error.
Not yet called by the frontend (the funnel is wired up in 7b-ii).
"""

import json

from fastapi import APIRouter, Request
from pydantic import ValidationError

from app.api.request_body import (
    PayloadTooLarge,
    invalid_json_response,
    read_body,
    too_large_response,
    validation_error_response,
)
from app.services.questionnaire import (
    QuestionnaireAnswers,
    QuestionnaireScore,
    score_questionnaire,
)
from app.services.questionnaire.questionnaire_config import (
    MAX_DRAINED_BYTES,
    MAX_REQUEST_BYTES,
)

router = APIRouter(prefix="/api/services/questionnaire", tags=["services"])

NOT_JSON = "Send the questionnaire answers as a JSON object."
TOO_LARGE = f"Request body is larger than {MAX_REQUEST_BYTES // 1000} KB."


@router.post(
    "/score",
    response_model=QuestionnaireScore,
    summary="Score questionnaire answers: skin type, sensitivity, per-score estimates",
    responses={
        413: {"description": TOO_LARGE},
        422: {"description": "Malformed answers, an unknown key or an unknown value. "
                             "The offending values are never echoed."},
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": QuestionnaireAnswers.model_json_schema()}},
        }
    },
)
async def score(request: Request):
    try:
        body = await read_body(request, MAX_REQUEST_BYTES, MAX_DRAINED_BYTES)
    except PayloadTooLarge:
        return too_large_response(TOO_LARGE)
    try:
        answers = json.loads(body)
    except ValueError:
        return invalid_json_response(NOT_JSON)
    try:
        return score_questionnaire(answers)
    except ValidationError as exc:
        return validation_error_response(exc)
