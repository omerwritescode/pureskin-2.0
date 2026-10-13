"""A stand-in Ollama server on httpx2.MockTransport: records every request (path, body,
timeout) and whether each answer stream was closed. No test needs a real Ollama."""

import asyncio
import json

import anyio
import httpx2

TAG = "test-model:4b-q4_K_M"
DIGEST = "0f" * 32  # what the tests pin in chat_config.ALLOWED_MODELS
OTHER_DIGEST = "1e" * 32


def tag_entry(name: str = TAG, digest: str = DIGEST, **extra) -> dict:
    return {"name": name, "model": name, "digest": digest, "size": 3_300_000_000,
            "details": {"family": "test", "quantization_level": "Q4_K_M"}, **extra}


def piece(text: str, thinking: str | None = None) -> dict:
    message = {"role": "assistant", "content": text}
    if thinking is not None:
        message["thinking"] = thinking
    return {"model": TAG, "message": message, "done": False}


DONE = {"model": TAG, "message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop",
        "total_duration": 2_000_000_000, "load_duration": 5_000_000, "prompt_eval_count": 812,
        "prompt_eval_duration": 300_000_000, "eval_count": 42, "eval_duration": 1_500_000_000}


class RecordingStream(httpx2.AsyncByteStream):
    """The answer's NDJSON lines, one per read (optionally slow); records being closed."""

    def __init__(self, lines: list, delay: float = 0.0):
        self.lines = lines
        self.delay = delay
        self.sent = 0
        self.closed = False

    async def __aiter__(self):
        for line in self.lines:
            if self.delay:
                await asyncio.sleep(self.delay)
            self.sent += 1
            yield (line if isinstance(line, str) else json.dumps(line)).encode() + b"\n"

    async def aclose(self) -> None:
        # As httpcore2's own close does (PoolByteStream.aclose): it awaits the connection, and
        # shields that from a cancelled task (httpx2 itself calls it unshielded).
        with anyio.CancelScope(shield=True):
            await asyncio.sleep(0)
            self.closed = True


class MockOllama:
    def __init__(self, *, models=None, version: str = "0.35.1", chat_lines=None, chat_status: int = 200,
                 tags_status: int = 200, tags_body=None, fail: Exception | None = None, delay: float = 0.0):
        self.models = [tag_entry()] if models is None else models
        self.version = version
        self.chat_lines = [piece("Reapply every two hours [kb-sun-sunscreen-use]. "), DONE] \
            if chat_lines is None else chat_lines
        self.chat_status = chat_status
        self.tags_status = tags_status
        self.tags_body = tags_body
        self.fail = fail  # raised for every request (e.g. httpx2.ConnectError)
        self.delay = delay
        self.requests: list[dict] = []
        self.streams: list[RecordingStream] = []

    @property
    def paths(self) -> list[str]:
        return [r["path"] for r in self.requests]

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append({"method": request.method, "path": request.url.path, "url": str(request.url),
                              "body": json.loads(request.content) if request.content else None,
                              "timeout": request.extensions.get("timeout")})
        if self.fail is not None:
            raise self.fail
        if request.url.path == "/api/version":
            return httpx2.Response(200, json={"version": self.version})
        if request.url.path == "/api/tags":
            if self.tags_body is not None:
                return httpx2.Response(self.tags_status, content=self.tags_body)
            return httpx2.Response(self.tags_status, json={"models": self.models})
        if request.url.path == "/api/chat":
            stream = RecordingStream(self.chat_lines, self.delay)
            self.streams.append(stream)
            return httpx2.Response(self.chat_status, stream=stream)
        return httpx2.Response(404, json={"error": "not found"})

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self.handler)
