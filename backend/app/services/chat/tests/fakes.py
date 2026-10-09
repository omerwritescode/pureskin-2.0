"""A scripted stand-in for the model client: no test ever needs Ollama."""

import asyncio

from app.services.chat.llm import LLMUnavailable


class FakeLLM:
    def __init__(self, pieces=(), available: bool = True, reason: str = "unreachable", delay: float = 0.0,
                 fail_after: int | None = None):
        self.pieces = list(pieces)
        self.available = available
        self.reason = reason
        self.delay = delay
        self.fail_after = fail_after  # raise mid-stream after this many pieces
        self.calls: list[list[dict]] = []  # the messages of every stream_chat call
        self.availability_checks = 0
        self.closed = False  # the stream was closed (finished, stopped by the gate, or aborted)

    async def check_available(self) -> None:
        self.availability_checks += 1
        if not self.available:
            raise LLMUnavailable(self.reason)

    async def stream_chat(self, messages: list[dict], options: dict):
        self.calls.append(messages)
        try:
            for i, piece in enumerate(self.pieces):
                if self.fail_after is not None and i == self.fail_after:
                    raise LLMUnavailable("stream broke")
                if self.delay:
                    await asyncio.sleep(self.delay)
                yield piece
        finally:
            self.closed = True


def collect(agen) -> list:
    async def run():
        return [event async for event in agen]
    return asyncio.run(run())
