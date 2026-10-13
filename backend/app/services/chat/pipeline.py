"""One chat turn, as a stream of events (7d).

Order, fixed:
1. the red-flag router: a template never touches the model, and is served even when Ollama
   is down (a deliberate, documented exception to "no model, 503");
2. the model's availability (LLMUnavailable -> the endpoint's 503; no fallback answer);
3. retrieval (frozen BM25 and its no-answer line), then term coverage, then the ingredient
   check (an ingredient no note mentions and no routine product contains): any of them ->
   the fixed "I don't know", no model call;
4. context (budgeted; if even the rules, profile, one note and the question don't fit, the
   fixed "I don't know", no retry), then the one generation slot (taken: LLMBusy, the
   endpoint's 503), then the model's answer through the gate: checked sentence by sentence
   as it streams, released when the stream ends (a [NO_ANSWER] anywhere: the fixed reply);
5. caution lines (soft flags, or groups matched only in history) after any answer.

Logging: one line per turn (log_turn): a request id, an outcome code, the model's tag,
timings and counts only. Never the message, history, prompt, answer, chunk ids, the
red-flag group or the user.
"""

import logging
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field

import anyio

from . import chat_config as cfg
from . import redflags
from .context import ContextTooLarge, ProfileContext, build_messages
from .coverage import covered
from .gate import Gate
from .ingredient_check import unsupported
from .llm import LLMBusy, LLMClient, LLMUnavailable
from .redflags import Turn
from .retrieval import BM25Index, retrieve

logger = logging.getLogger("pureskin.chat")

# The usage counts that go into the log line, in order.
USAGE_FIELDS = ("prompt_tokens", "output_tokens", "load_ms", "prompt_ms", "eval_ms", "done_reason", "thinking")


def log_turn(request_id: str, outcome: str, model: str, **counts) -> None:
    """The one log line per request: metadata only (a test checks every path)."""
    extra = " ".join(f"{k}={v}" for k, v in counts.items() if v is not None)
    logger.info("chat turn: request=%s outcome=%s model=%s %s", request_id, outcome, model or "-", extra)


@dataclass(frozen=True)
class Event:
    type: str  # "start", "text", "caution", "citations", "end"
    data: dict = field(default_factory=dict)


def _sentences(text: str) -> list[Event]:
    return [Event("text", {"text": s, "cites": []}) for s in redflags.split_sentences(text)]


def _citations(kb, cited: list[str]) -> Event:
    """The cited notes with their sources: the publisher is shown on every chip (NIA asks for
    credit); repository sources have no link."""
    chunks = []
    for cid in cited:
        if cid == "profile":
            continue
        c = kb.get(cid)
        chunks.append({"id": c.id, "title": c.title, "sources": [
            {"publisher": s.publisher, "url": s.url if s.is_web else None, "role": s.role} for s in c.sources]})
    return Event("citations", {"chunks": chunks})


async def respond(message: str, history: Sequence[Turn], llm: LLMClient, *, kb, index: BM25Index,
                  profile: ProfileContext | None, slot=None, request_id: str = "-") -> AsyncIterator[Event]:
    """`slot` (limits.GenerationSlot) is taken just before the model is called; None: no limit."""
    started = time.perf_counter()
    stats = {"outcome": "error", "released": 0, "blocked": {}, "first_ms": None}
    usage: dict = {}

    def mark_first():
        if stats["first_ms"] is None:
            stats["first_ms"] = round((time.perf_counter() - started) * 1000)

    try:
        route = redflags.route(message, history)
        if route.kind == "template":
            stats["outcome"] = "template"
            yield Event("start", {"route": "template"})
            for event in _sentences(route.template_text):
                mark_first()
                yield event
            yield Event("end", {"reason": "template"})
            return
        try:
            await llm.check_available()
        except LLMUnavailable:
            stats["outcome"] = "unavailable"
            raise
        result = retrieve(index, message)
        context = None
        if not result.answerable:
            stats["outcome"] = "no_answer_line"
        elif not covered(message, kb.get(result.ids[0])):
            stats["outcome"] = "no_answer_coverage"
        elif unsupported(message, kb, profile.ingredients if profile else frozenset()):
            stats["outcome"] = "no_answer_ingredient"  # names an ingredient the notes and routine lack
        else:
            try:
                context = build_messages(message, history, [kb.get(cid) for cid in result.ids], profile)
            except ContextTooLarge:  # the rules, profile, one note and the question don't fit: no retry
                stats["outcome"] = "no_answer_context"
        if context is None:
            yield Event("start", {"route": "no_answer"})
            for event in _sentences(cfg.NO_ANSWER_TEXT):
                mark_first()
                yield event
        else:
            if slot is not None and not slot.try_acquire():
                stats["outcome"] = "busy"
                raise LLMBusy()
            try:
                gate = Gate(context.chunk_ids, profile.products if profile else {})
                stats["outcome"] = "stopped"  # until the answer ends: the client went away
                yield Event("start", {"route": "model"})
                cited: list[str] = []
                stream = llm.stream_chat(list(context.messages), dict(cfg.MODEL_OPTIONS), usage)
                try:
                    async for piece in stream:
                        gate.feed(piece)  # checked now; released only when the stream ends (F1)
                        if gate.stopped:
                            break
                except LLMUnavailable:
                    stats["outcome"] = "stream_error"
                    raise
                finally:
                    # A gate stop or a client abort ends the model's stream. Shielded: after a
                    # client abort the task is cancelled, and the close must still happen.
                    with anyio.CancelScope(shield=True):
                        await stream.aclose()
                for out in gate.finish(truncated=usage.get("done_reason") == "length"):
                    cited += [c for c in out.cites if c not in cited]
                    mark_first()
                    yield Event("text", {"text": out.text, "cites": list(out.cites)})
                stats["released"] = gate.released_sentences
                stats["blocked"] = dict(gate.counts)
                if gate.stop_reason == "no_answer" or not gate.stopped and gate.released_sentences == 0:
                    stats["outcome"] = "no_answer_model"
                    for event in _sentences(cfg.NO_ANSWER_TEXT):
                        mark_first()
                        yield event
                elif gate.stopped:
                    stats["outcome"] = f"gate_{gate.stop_reason}"
                    for event in _sentences(cfg.GATE_STOP_TEXT):
                        mark_first()
                        yield event
                else:
                    stats["outcome"] = "answered"
                yield _citations(kb, cited)
            finally:
                if slot is not None:
                    slot.release()
        for text in route.caution_texts:
            yield Event("caution", {"text": text})
        yield Event("end", {"reason": stats["outcome"]})
    finally:
        log_turn(request_id, stats["outcome"], getattr(llm, "model", None), released=stats["released"],
                 blocked=stats["blocked"] or None, first_ms=stats["first_ms"],
                 total_ms=round((time.perf_counter() - started) * 1000),
                 **{k: usage.get(k) for k in USAGE_FIELDS})
