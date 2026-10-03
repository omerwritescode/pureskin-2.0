"""Request handling shared by the endpoints that take personal data (photos, free text).

They read and parse their body by hand, rather than through FastAPI's Pydantic body
parameters, for two reasons:
- an oversized upload is refused before it is buffered (413);
- they control their own errors: the 422s here go through
  app/api/validation_errors.py, so the user's photo or free text never comes back.
"""

from fastapi import Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.api.validation_errors import public_errors


class PayloadTooLarge(Exception):
    pass


async def read_body(request: Request, max_bytes: int, max_drained_bytes: int) -> bytes:
    """The request body, or PayloadTooLarge once it exceeds max_bytes.

    Bytes are counted as they arrive, so chunked uploads (no Content-Length) are capped
    too. Past the limit nothing more is kept, but the rest is drained (up to
    max_drained_bytes) so the client can actually read the 413 response.
    """
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > max_drained_bytes:
        raise PayloadTooLarge
    body, received = bytearray(), 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > max_drained_bytes:
            raise PayloadTooLarge
        if received <= max_bytes:
            body += chunk
    if received > max_bytes:
        raise PayloadTooLarge
    return bytes(body)


def too_large_response(detail: str) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_413_CONTENT_TOO_LARGE, content={"detail": detail})


def validation_error_response(exc: ValidationError, prefix: tuple = ("body",)) -> JSONResponse:
    """FastAPI's 422 shape ({"detail": [{loc, msg, type}]}) without the input values."""
    errors = [{**e, "loc": prefix + tuple(e["loc"])} for e in exc.errors(include_url=False)]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": public_errors(errors, include_ctx=False)},
    )


def invalid_json_response(message: str) -> JSONResponse:
    error = {"loc": ("body",), "msg": message, "type": "json_invalid"}
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": public_errors([error], include_ctx=False)},
    )
