"""One chat turn, as a stream of events (7d).

Order, fixed:
1. the red-flag router: a template never touches the model, and is served even when Ollama
   is down (a deliberate, documented exception to "no model, 503");
2. the model's availability (LLMUnavailable -> the endpoint's 503; no fallback answer);
3. retrieval (frozen BM25 and its no-answer line), then term coverage: either below its
   minimum -> the fixed "I don't know", no model call;
4. context (budgeted; if even the rules, profile, one note and the question don't fit, the
   fixed "I don't know", no retry), then the model's answer through the gate, sentence by
   sentence;
5. caution lines (soft flags, or groups matched only in history) after any answer.

Logging: one line per turn with an outcome code and counts only. Never the message,
history, prompt, answer, chunk ids or the red-flag group.
"""

import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field

from . import chat_config as cfg
from . import redflags
from .context import ContextTooLarge, ProfileContext, build_messages
from .coverage import covered
from .gate import Gate
from .llm import LLMClient, LLMUnavailable
from .redflags import Turn
from .retrieval import BM25Index, retrieve

logger = logging.getLogger("pureskin.chat")


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
                  profile: ProfileContext | None) -> AsyncIterator[Event]:
    stats = {"outcome": "error", "released": 0, "blocked": {}}
    try:
        route = redflags.route(message, history)
        if route.kind == "template":
            stats["outcome"] = "template"
            yield Event("start", {"route": "template"})
            for event in _sentences(route.template_text):
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
        else:
            try:
                context = build_messages(message, history, [kb.get(cid) for cid in result.ids], profile)
            except ContextTooLarge:  # the rules, profile, one note and the question don't fit: no retry
                stats["outcome"] = "no_answer_context"
        if context is None:
            yield Event("start", {"route": "no_answer"})
            for event in _sentences(cfg.NO_ANSWER_TEXT):
                yield event
        else:
            gate = Gate(context.chunk_ids, profile.products if profile else {})
            yield Event("start", {"route": "model"})
            cited: list[str] = []
            stream = llm.stream_chat(list(context.messages), dict(cfg.MODEL_OPTIONS))
            try:
                async for piece in stream:
                    for out in gate.feed(piece):
                        cited += [c for c in out.cites if c not in cited]
                        yield Event("text", {"text": out.text, "cites": list(out.cites)})
                    if gate.stopped:
                        break
            finally:
                await stream.aclose()  # a stop or a client abort ends the model's stream
            for out in gate.finish():
                cited += [c for c in out.cites if c not in cited]
                yield Event("text", {"text": out.text, "cites": list(out.cites)})
            stats["released"] = gate.released_sentences
            stats["blocked"] = dict(gate.counts)
            if gate.stop_reason == "no_answer" and gate.released_sentences == 0 or \
                    not gate.stopped and gate.released_sentences == 0:
                stats["outcome"] = "no_answer_model"
                for event in _sentences(cfg.NO_ANSWER_TEXT):
                    yield event
            elif gate.stopped:
                stats["outcome"] = f"gate_{gate.stop_reason}"
                for event in _sentences(cfg.GATE_STOP_TEXT):
                    yield event
            else:
                stats["outcome"] = "answered"
            yield _citations(kb, cited)
        for text in route.caution_texts:
            yield Event("caution", {"text": text})
        yield Event("end", {"reason": stats["outcome"]})
    finally:
        logger.info("chat turn: outcome=%s released=%d blocked=%s", stats["outcome"], stats["released"],
                    stats["blocked"])
