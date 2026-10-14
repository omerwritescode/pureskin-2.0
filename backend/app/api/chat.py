"""POST /api/chat and GET /api/chat/status (7d, Unit 3): the Skin-Profile-grounded chat.

The turn itself is app/services/chat/pipeline.py (router, retrieval, context, model, gate);
this module checks the request, applies the limits and streams the events.

POST /api/chat, signed in, body {"message": str, "history": [{"role", "content"}]} (at most
3 exchanges; nothing else is accepted):

| Status | Body |
|---|---|
| 200 | application/x-ndjson, one event per line (below) |
| 401 | not signed in |
| 413 | {"detail": ...}: body over 16 KB |
| 422 | {"detail": [{loc, msg, type}]}: malformed body (input never echoed) |
| 429 | {"detail": ...} and Retry-After: over 10 a minute or 100 a day. A message routed to a red-flag template counts only toward the templates' own limit (30 a minute, 300 a day), so it is still served past the model's. |
| 503 | {"detail", "reason"}: the model can't be used (chat_config.STATUS_REASONS), or "busy" with Retry-After (one answer at a time). Red-flag templates are served even when Ollama is down; while another answer is being generated, templates and the fixed "I don't know" are still served. |

Events: {"type": "start", "route", "request_id", "config_versions"}; {"type": "text", "text",
"cites"} per sentence; {"type": "citations", "chunks"}; {"type": "caution", "text"};
{"type": "end", "reason"}; and {"type": "error", "code"} if the model fails after the start.

Nothing is stored. One log line per request (pipeline.log_turn), never any text.
"""

import json
import logging
import uuid
from functools import cache
from typing import Annotated, Literal

import anyio
from fastapi import APIRouter, Depends, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.request_body import (
    PayloadTooLarge,
    invalid_json_response,
    read_body,
    too_large_response,
    validation_error_response,
)
from app.core.config import settings
from app.models import User
from app.services.chat import chat_config as cfg
from app.services.chat import redflags
from app.services.chat.context import load_profile_context
from app.services.chat.kb import load_kb
from app.services.chat.limits import ChatLimits
from app.services.chat.llm import LLMBusy, LLMClient, LLMUnavailable
from app.services.chat.ollama import ChatStatus, OllamaClient
from app.services.chat.pipeline import Event, log_turn, respond
from app.services.chat.redflags import Turn
from app.services.chat.retrieval import build_index

router = APIRouter(prefix="/api/chat", tags=["chat"])
logger = logging.getLogger("uvicorn.error")  # the startup line, next to the other services'

TOO_LARGE = f"The chat request is over {cfg.MAX_BODY_BYTES // 1024} KB."
NOT_JSON = 'Send JSON of the form {"message": "...", "history": [{"role": "user", "content": "..."}]}.'


class UserTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user"]
    content: Annotated[str, StringConstraints(min_length=1, max_length=cfg.MAX_MESSAGE_CHARS)]


class AssistantTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["assistant"]
    content: Annotated[str, StringConstraints(min_length=1, max_length=cfg.MAX_HISTORY_ASSISTANT_CHARS)]


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=cfg.MAX_MESSAGE_CHARS)]
    history: list[Annotated[UserTurn | AssistantTurn, Field(discriminator="role")]] = Field(
        default_factory=list, max_length=cfg.MAX_HISTORY_TURNS)


class ChatStatusOut(BaseModel):
    available: bool
    reason: Literal[tuple(cfg.STATUS_REASONS)] | None
    detail: str
    model: str | None


# --- Dependencies (tests override them) -----------------------------------------------
_llm: OllamaClient | None = None
_limits = ChatLimits()


def get_chat_llm() -> LLMClient:
    """The process's one Ollama client, from OLLAMA_HOST and CHAT_MODEL."""
    global _llm
    if _llm is None:
        _llm = OllamaClient(settings.OLLAMA_HOST, settings.CHAT_MODEL)
    return _llm


async def close_chat_llm() -> None:
    global _llm
    if _llm is not None:
        client, _llm = _llm, None
        await client.aclose()


def get_chat_limits() -> ChatLimits:
    return _limits


def get_profile_loader():
    return load_profile_context


@cache
def knowledge():
    """The knowledge base and its BM25 index, loaded once."""
    kb = load_kb()
    return kb, build_index(kb)


async def probe_chat(llm: OllamaClient | None = None) -> ChatStatus:
    """At startup: one log line saying whether the chat can be used. Only /api/version and
    /api/tags (1 s each); never anything that loads or warms the model."""
    llm = llm or get_chat_llm()
    result = await llm.status(with_version=True)
    if result.available:
        logger.info("Chat: available (%s, digest %s, Ollama %s)", result.model, result.digest[:12],
                    result.ollama_version)
    else:
        logger.warning("Chat unavailable (%s): %s", result.reason, result.detail)
    return result


# --- Streaming ---------------------------------------------------------------------------
def _line(event: Event) -> bytes:
    return (json.dumps({"type": event.type, **event.data}, ensure_ascii=False) + "\n").encode()


async def _ndjson(start: Event, events):
    try:
        yield _line(start)
        async for event in events:
            yield _line(event)
    except LLMUnavailable as exc:  # the model failed after the headers went out
        yield _line(Event("error", {"code": exc.reason}))
    finally:
        with anyio.CancelScope(shield=True):
            await events.aclose()


class ClosingStreamingResponse(StreamingResponse):
    """Closes its body when the response ends, however it ends. When the client goes away,
    Starlette cancels the body mid-stream but doesn't close it; this closes it at once, so
    the model's stream is closed (and the generation slot freed) without waiting for the
    garbage collector."""

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                await self.body_iterator.aclose()


# --- Endpoints ---------------------------------------------------------------------------
@router.get("/status", response_model=ChatStatusOut, summary="Whether the chat's model can be used, and why not")
async def chat_status(user: User = Depends(get_current_user), llm: OllamaClient = Depends(get_chat_llm)):
    result = await llm.status()
    return ChatStatusOut(available=result.available, reason=result.reason, detail=result.detail, model=result.model)


@router.post(
    "",
    summary="One chat turn, streamed as NDJSON events (nothing stored)",
    responses={
        200: {"content": {"application/x-ndjson": {}}, "description": "One JSON event per line."},
        413: {"description": TOO_LARGE},
        422: {"description": "Malformed body (input never echoed)."},
        429: {"description": "Over the per-user limit; see Retry-After."},
        503: {"description": "The model can't be used (reason), or busy (Retry-After)."},
    },
    openapi_extra={
        "requestBody": {"required": True, "content": {"application/json": {"schema": ChatRequest.model_json_schema()}}}
    },
)
async def chat(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db),
               llm: LLMClient = Depends(get_chat_llm), limits: ChatLimits = Depends(get_chat_limits),
               load_profile=Depends(get_profile_loader)):
    request_id = uuid.uuid4().hex[:12]
    model = getattr(llm, "model", None)
    # Parsed by hand (as the scan endpoints do): an oversized body is refused before it is
    # buffered, and no error can echo the message.
    try:
        body = await read_body(request, cfg.MAX_BODY_BYTES, cfg.MAX_DRAINED_BYTES)
    except PayloadTooLarge:
        log_turn(request_id, "too_large", model)
        return too_large_response(TOO_LARGE)
    try:
        payload = json.loads(body)
    except ValueError:
        log_turn(request_id, "invalid", model)
        return invalid_json_response(NOT_JSON)
    try:
        req = ChatRequest.model_validate(payload)
    except ValidationError as exc:
        log_turn(request_id, "invalid", model)
        return validation_error_response(exc)

    # Red-flag templates first (Unit 5): they never reach the model, so they count toward
    # their own limit, not the model's. The pipeline routes the same message and history
    # again with the same function, so it serves the template this limit was chosen for.
    history = [Turn(t.role, t.content) for t in req.history]
    templated = redflags.route(req.message, history).kind == "template"
    wait = (limits.template_rate if templated else limits.rate).hit(user.id)
    if wait is not None:
        log_turn(request_id, "rate_limited_template" if templated else "rate_limited", model)
        return JSONResponse(status_code=status.HTTP_429_TOO_MANY_REQUESTS, content={"detail": cfg.RATE_LIMITED_TEXT},
                            headers={"Retry-After": str(wait)})

    profile = None if templated else await run_in_threadpool(load_profile, db, user)  # a template never reads it
    db.close()  # nothing more to read: no connection is held while the answer streams
    kb, index = knowledge()
    events = respond(req.message, history, llm, kb=kb, index=index, profile=profile, slot=limits.slot,
                     request_id=request_id)
    # The first event decides the status code: everything that can fail before an answer
    # starts (the model's availability, the busy slot) fails here, as a 503.
    try:
        first = await anext(events)
    except LLMUnavailable as exc:
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            content={"detail": cfg.STATUS_REASONS.get(exc.reason, cfg.STATUS_REASONS["unreachable"]),
                                     "reason": exc.reason})
    except LLMBusy:
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            content={"detail": cfg.BUSY_TEXT, "reason": "busy"},
                            headers={"Retry-After": str(cfg.BUSY_RETRY_AFTER_SECONDS)})
    start = Event("start", {**first.data, "request_id": request_id, "config_versions": {
        "chat": cfg.CHAT_CONFIG_VERSION, "kb": kb.version, "model": model, "model_digest": getattr(llm, "digest", None)}})
    return ClosingStreamingResponse(_ndjson(start, events), media_type="application/x-ndjson",
                                    headers={"Cache-Control": "no-store"})
