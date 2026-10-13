"""A scripted stand-in for the model client: no test ever needs Ollama."""

import asyncio

from app.services.chat.llm import LLMUnavailable


class FakeLLM:
    model = "fake-model:1b"

    def __init__(self, pieces=(), available: bool = True, reason: str = "unreachable", delay: float = 0.0,
                 fail_after: int | None = None, gate: asyncio.Event | None = None, done_reason: str = "stop"):
        self.pieces = list(pieces)
        self.available = available
        self.reason = reason
        self.delay = delay
        self.fail_after = fail_after  # raise mid-stream after this many pieces
        self.gate = gate  # if set, the stream waits for it before its first piece
        self.done_reason = done_reason
        self.calls: list[list[dict]] = []  # the messages of every stream_chat call
        self.options: list[dict] = []
        self.availability_checks = 0
        self.closed = False  # the stream was closed (finished, stopped by the gate, or aborted)

    async def check_available(self) -> None:
        self.availability_checks += 1
        if not self.available:
            raise LLMUnavailable(self.reason)

    async def stream_chat(self, messages: list[dict], options: dict, usage: dict | None = None):
        self.calls.append(messages)
        self.options.append(options)
        try:
            if self.gate is not None:
                await self.gate.wait()
            for i, piece in enumerate(self.pieces):
                if self.fail_after is not None and i == self.fail_after:
                    raise LLMUnavailable("stream_broken")
                if self.delay:
                    await asyncio.sleep(self.delay)
                yield piece
            if usage is not None:
                usage.update({"prompt_tokens": 900, "output_tokens": len(self.pieces), "load_ms": 0,
                              "prompt_ms": 50, "eval_ms": 100, "done_reason": self.done_reason})
        finally:
            self.closed = True


def collect(agen) -> list:
    async def run():
        return [event async for event in agen]
    return asyncio.run(run())
