"""The model client's interface (7d). The Ollama client is ollama.py (Unit 3); tests use a
fake (tests/fakes.py), so no test ever needs Ollama.
"""

from collections.abc import AsyncIterator
from typing import Protocol


class LLMUnavailable(Exception):
    """The model can't be used (Ollama unreachable, model missing, moved tag, cloud tag,
    non-loopback host, no pinned model) or its stream broke. Before an answer starts, the
    endpoint answers 503 with the reason; after, an "error" event. Never a fallback answer."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class LLMBusy(Exception):
    """Another answer is being generated (one at a time: one GPU). The endpoint's 503 with
    Retry-After."""


class LLMClient(Protocol):
    model: str  # the tag, for the log line and the stream's config versions

    async def check_available(self) -> None:
        """Raise LLMUnavailable if the model can't be used."""

    def stream_chat(self, messages: list[dict], options: dict, usage: dict | None = None) -> AsyncIterator[str]:
        """The model's answer, piece by piece (never its thinking). At the end, `usage` gets
        the counts: prompt_tokens, output_tokens, done_reason, thinking (pieces dropped) and
        the model's own timings in ms (load_ms, prompt_ms, eval_ms, total_ms)."""
