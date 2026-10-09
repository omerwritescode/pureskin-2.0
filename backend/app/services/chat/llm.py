"""The model client's interface (7d). Unit 3 adds the Ollama client; tests use a fake
(tests/fakes.py), so no test ever needs Ollama.
"""

from collections.abc import AsyncIterator
from typing import Protocol


class LLMUnavailable(Exception):
    """The model can't be used (Ollama unreachable, model missing, moved tag, cloud tag,
    non-loopback host). The endpoint answers 503 with the reason; never a fallback answer."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class LLMClient(Protocol):
    async def check_available(self) -> None:
        """Raise LLMUnavailable if the model can't be used."""

    def stream_chat(self, messages: list[dict], options: dict) -> AsyncIterator[str]:
        """The model's answer, piece by piece (never its thinking)."""
