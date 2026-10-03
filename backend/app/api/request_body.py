"""Request handling shared by the endpoints that take personal data (photos, free text).

They read and parse their body by hand, rather than through FastAPI's Pydantic body
parameters, for two reasons:
- an oversized upload is refused before it is buffered (413);
- an error never echoes the input. FastAPI's default 422 includes each offending value
  under "input", which here would be the user's photo or free text.
"""

from fastapi import Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError

MAX_LOC_PART_CHARS = 64  # an unknown key is echoed in "loc"; keep it short


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


def _error(loc: tuple, msg: str, type_: str) -> dict:
    return {
        "loc": [p[:MAX_LOC_PART_CHARS] if isinstance(p, str) else p for p in loc],
        "msg": msg,
        "type": type_,
    }


def validation_error_response(exc: ValidationError, prefix: tuple = ("body",)) -> JSONResponse:
    """FastAPI's 422 shape ({"detail": [{loc, msg, type}]}) without the input values."""
    errors = exc.errors(include_url=False, include_context=False, include_input=False)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": [_error(prefix + tuple(e["loc"]), e["msg"], e["type"]) for e in errors]},
    )


def invalid_json_response(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": [_error(("body",), message, "json_invalid")]},
    )
