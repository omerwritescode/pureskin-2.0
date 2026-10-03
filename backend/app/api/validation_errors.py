"""Validation errors that are safe to send back: loc, msg and type, never the input.

FastAPI's default 422 echoes each submitted value under "input" (passwords, emails,
photos, free text), and some validators also copy the value, or parts of it, into
"msg" and "ctx" (email-validator's reason quotes the offending characters). Used by
the global RequestValidationError handler in main.py and by the endpoints that parse
their own bodies (app/api/request_body.py). Nothing here logs anything.
"""

from collections.abc import Iterable, Iterator

# ctx keys kept in the response: numeric limits from the schema, never the input.
SAFE_CTX_KEYS = ("min_length", "max_length", "ge", "le", "gt", "lt")
# ctx values that come from the schema, so they may stay inside msg
# ("Input should be 'oily' or 'dry'", "String should match pattern '...'").
SCHEMA_CTX_KEYS = (*SAFE_CTX_KEYS, "expected", "pattern")
MAX_LOC_PART_CHARS = 64  # an unknown key's name is echoed in loc; keep it short
MIN_ECHO_CHARS = 3  # shorter submitted strings can't be told apart from normal words
GENERIC_MSG = "Invalid value"


def _strings(value, depth: int = 0) -> Iterator[str]:
    """Every string inside a submitted value (nested dicts and lists included)."""
    if isinstance(value, str):
        yield value
    elif depth < 5 and isinstance(value, dict):
        for k, v in value.items():
            yield from _strings(k, depth + 1)
            yield from _strings(v, depth + 1)
    elif depth < 5 and isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings(v, depth + 1)


def _public_msg(error: dict) -> str:
    msg = str(error.get("msg", ""))
    # Validator-supplied text interpolated into msg (e.g. email-validator's "reason"):
    # it may quote the input, so cut it out, keeping the generic part before it.
    for key, value in (error.get("ctx") or {}).items():
        if key not in SCHEMA_CTX_KEYS and isinstance(value, str) and value and value in msg:
            msg = msg.replace(value, "").strip().rstrip(":").strip()
    if any(len(s) >= MIN_ECHO_CHARS and s in msg for s in _strings(error.get("input"))):
        return GENERIC_MSG
    return msg or GENERIC_MSG


def public_errors(errors: Iterable[dict], *, include_ctx: bool = True) -> list[dict]:
    """Errors as {loc, msg, type[, ctx]}, without the submitted input anywhere."""
    out = []
    for error in errors:
        item = {
            "loc": [
                p[:MAX_LOC_PART_CHARS] if isinstance(p, str) else p for p in error.get("loc", ())
            ],
            "msg": _public_msg(error),
            "type": error.get("type", "value_error"),
        }
        ctx = {
            k: v
            for k, v in (error.get("ctx") or {}).items()
            if k in SAFE_CTX_KEYS and isinstance(v, (int, float)) and not isinstance(v, bool)
        }
        if include_ctx and ctx:
            item["ctx"] = ctx
        out.append(item)
    return out
