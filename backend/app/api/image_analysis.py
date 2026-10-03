"""POST /api/services/image/analyze: the Image Analysis service, exposed on its own.

No auth, because the onboarding funnel runs before signup. Stateless: the photo is
decoded in memory, scored, and discarded. It is never stored, written to a temp file,
logged, or echoed back in an error. Not yet called by the frontend (wired in step 7b).
"""

import json
from typing import Annotated, Literal

from fastapi import APIRouter, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.request_body import PayloadTooLarge, read_body, too_large_response
from app.services.image_analysis import ImageRejected, ModelUnavailable, analyze_image
from app.services.image_analysis.scoring_config import MAX_DRAINED_BYTES, MAX_REQUEST_BYTES

router = APIRouter(prefix="/api/services/image", tags=["services"])

Score = Annotated[int, Field(ge=1, le=100)]  # matches the skin_profiles CHECK constraints
SkinType = Literal["oily", "dry", "combination", "normal", "sensitive"]

BAD_REQUEST = 'Send JSON of the form {"image": "<base64 JPEG or data URL>"}.'
TOO_LARGE = (
    f"Request body is larger than {MAX_REQUEST_BYTES // 1_000_000} MB. "
    "Send a JPEG downsized to at most 720 px on its longest side."
)


class Quality(BaseModel):
    ok: bool
    issues: list[str]  # hard rejections when ok is false, soft warnings when true


class ImageAnalysisResponse(BaseModel):
    acne_score: Score
    redness_score: Score
    wrinkle_score: Score
    pigmentation_score: Score
    pore_score: Score
    skin_type_prediction: SkinType | None
    skin_type_confidence: float | None = Field(ge=0, le=1)
    skin_type_labels_supported: list[SkinType]
    quality: Quality
    model_version: str


class ImageRejectedResponse(BaseModel):
    quality: Quality


@router.post(
    "/analyze",
    response_model=ImageAnalysisResponse,
    summary="Score a selfie: five 1-100 skin scores plus photo-quality feedback",
    responses={
        400: {"description": BAD_REQUEST},
        413: {"description": TOO_LARGE},
        422: {"model": ImageRejectedResponse, "description": "Photo unusable; no scores."},
        503: {"description": "Face landmark model not downloaded."},
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["image"],
                        "properties": {
                            "image": {
                                "type": "string",
                                "description": "Base64 JPEG/PNG, bare or as a data URL",
                            }
                        },
                    }
                }
            },
        }
    },
)
async def analyze(request: Request):
    # The body is read and parsed by hand, rather than through a Pydantic model, so that
    # an oversized upload is refused before it is buffered, and so a malformed request is
    # never echoed back (FastAPI's default validation errors include the input value,
    # which here would be the user's photo).
    try:
        body = await read_body(request, MAX_REQUEST_BYTES, MAX_DRAINED_BYTES)
    except PayloadTooLarge:
        return too_large_response(TOO_LARGE)
    try:
        payload = json.loads(body)
    except ValueError:
        payload = None
    image = payload.get("image") if isinstance(payload, dict) else None
    if not isinstance(image, str) or not image.strip():
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST, content={"detail": BAD_REQUEST}
        )

    try:
        # CPU-bound (~0.1-0.3 s); run it off the event loop.
        return await run_in_threadpool(analyze_image, image)
    except ImageRejected as exc:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"quality": {"ok": False, "issues": exc.issues}},
        )
    except ModelUnavailable as exc:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(exc)}
        )
