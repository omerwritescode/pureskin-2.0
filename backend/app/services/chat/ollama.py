"""The Ollama client (7d, Unit 3): a local model on this machine's loopback interface only.

- The host (OLLAMA_HOST) must be a loopback address: 127.0.0.0/8, ::1, or "localhost"
  (taken as 127.0.0.1, never looked up). Anything else, including 0.0.0.0, gets no request
  at all: the reason is "non_loopback_host".
- The model (CHAT_MODEL) must be pinned to its digest in chat_config.ALLOWED_MODELS and must
  not be a cloud tag. Ollama must list it (/api/tags) with exactly that digest; otherwise
  "missing_model" or "moved_tag". Every turn checks (one /api/tags call, about a millisecond
  on loopback), so a re-pull that moves the tag fails closed at once.
- /api/chat is streamed as NDJSON with "think": false and the pinned sampling options. Any
  thinking the model still sends is dropped and counted, never passed on.
- Proxy environment variables are ignored (trust_env=False): the prompt can't be routed
  off the machine. No redirects are followed.
- Nothing is logged here. Closing the answer's stream (the gate stopping it, or the client
  going away) closes the HTTP response, and Ollama stops generating.
"""

import ipaddress
import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from urllib.parse import urlsplit

import anyio
import httpx2

from . import chat_config as cfg
from .llm import LLMUnavailable

_CLOUD = re.compile(cfg.CLOUD_TAG_PATTERN)


def loopback_url(host: str | None) -> str | None:
    """OLLAMA_HOST as a base URL ("http://127.0.0.1:11434"), or None unless it points at
    this machine's loopback interface. Accepts Ollama's own forms: "127.0.0.1",
    "127.0.0.1:11434", "http://localhost:11434", "[::1]:11434"."""
    raw = (host or "").strip() or cfg.OLLAMA_DEFAULT_HOST
    if "://" not in raw:
        raw = f"http://{raw}"
    try:
        parts = urlsplit(raw)
        port = parts.port or cfg.OLLAMA_DEFAULT_PORT
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or parts.username or parts.password or parts.query \
            or parts.fragment or parts.path not in ("", "/") or not parts.hostname:
        return None
    name = "127.0.0.1" if parts.hostname == "localhost" else parts.hostname
    try:
        ip = ipaddress.ip_address(name)
    except ValueError:
        return None  # a host name: never resolved
    if not ip.is_loopback:
        return None
    return f"{parts.scheme}://{f'[{ip}]' if ip.version == 6 else ip}:{port}"


def is_cloud_tag(tag: str) -> bool:
    return bool(_CLOUD.search(tag.strip().lower()))


def _digest(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    return value.removeprefix("sha256:")


def _ms(nanoseconds) -> int | None:
    return round(nanoseconds / 1e6) if isinstance(nanoseconds, (int, float)) else None


def usage_from(done: dict) -> dict:
    """The counts from the stream's last line (done: true)."""
    return {
        "done_reason": done.get("done_reason"),
        "prompt_tokens": done.get("prompt_eval_count"),
        "output_tokens": done.get("eval_count"),
        "load_ms": _ms(done.get("load_duration")),
        "prompt_ms": _ms(done.get("prompt_eval_duration")),
        "eval_ms": _ms(done.get("eval_duration")),
        "total_ms": _ms(done.get("total_duration")),
    }


@dataclass(frozen=True)
class ChatStatus:
    available: bool
    reason: str | None  # a key of chat_config.STATUS_REASONS, None when available
    model: str | None
    digest: str | None  # the pinned digest
    ollama_version: str | None = None

    @property
    def detail(self) -> str:
        return cfg.STATUS_REASONS[self.reason] if self.reason else cfg.AVAILABLE_TEXT


class OllamaClient:
    def __init__(self, host: str | None, model: str | None, transport: httpx2.AsyncBaseTransport | None = None):
        self.model = (model or "").strip()
        self.digest = cfg.ALLOWED_MODELS.get(self.model)
        self.base_url = loopback_url(host)
        self._client = None
        if self.base_url is not None:
            self._client = httpx2.AsyncClient(
                base_url=self.base_url, transport=transport, trust_env=False, follow_redirects=False,
                timeout=httpx2.Timeout(cfg.READ_TIMEOUT_SECONDS, connect=cfg.CONNECT_TIMEOUT_SECONDS),
            )

    def _static_problem(self) -> str | None:
        """What is wrong before any request is made (no request ever goes to a bad host)."""
        if self.base_url is None:
            return "non_loopback_host"
        if self.model and is_cloud_tag(self.model):
            return "cloud_tag"
        if self.digest is None:
            return "unpinned_model"
        return None

    def _status(self, reason: str | None, version: str | None = None) -> ChatStatus:
        return ChatStatus(reason is None, reason, self.model or None, self.digest, version)

    async def status(self, with_version: bool = False) -> ChatStatus:
        """Whether the pinned model can be used. GET /api/tags (and /api/version if asked),
        each with a 1 s timeout; never anything that loads the model."""
        problem = self._static_problem()
        if problem:
            return self._status(problem)
        timeout = httpx2.Timeout(cfg.PROBE_TIMEOUT_SECONDS)
        version = None
        try:
            if with_version:
                response = await self._client.get("/api/version", timeout=timeout)
                response.raise_for_status()
                version = response.json().get("version")
            response = await self._client.get("/api/tags", timeout=timeout)
            response.raise_for_status()
            models = response.json().get("models") or []
        except (httpx2.HTTPError, ValueError, AttributeError):
            return self._status("unreachable")
        entry = next((m for m in models if isinstance(m, dict) and self.model in (m.get("name"), m.get("model"))),
                     None)
        if entry is None:
            return self._status("missing_model", version)
        if entry.get("remote_host") or entry.get("remote_model"):
            return self._status("cloud_tag", version)
        if _digest(entry.get("digest")) != self.digest:
            return self._status("moved_tag", version)
        return self._status(None, version)

    async def check_available(self) -> None:
        status = await self.status()
        if not status.available:
            raise LLMUnavailable(status.reason)

    async def stream_chat(self, messages: list[dict], options: dict, usage: dict | None = None) -> AsyncIterator[str]:
        problem = self._static_problem()
        if problem:
            raise LLMUnavailable(problem)
        usage = {} if usage is None else usage
        body = {"model": self.model, "messages": messages, "stream": True, "think": cfg.THINK, "options": options}
        try:
            response = await self._client.send(self._client.build_request("POST", "/api/chat", json=body), stream=True)
        except httpx2.HTTPError:
            raise LLMUnavailable("unreachable") from None
        try:
            if response.status_code != 200:
                raise LLMUnavailable("model_error")  # its body is never read or logged
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except ValueError:
                    raise LLMUnavailable("bad_stream") from None
                if not isinstance(data, dict) or "error" in data:
                    raise LLMUnavailable("model_error")
                message = data.get("message") or {}
                if message.get("thinking"):
                    usage["thinking"] = usage.get("thinking", 0) + 1
                content = message.get("content")
                if isinstance(content, str) and content:
                    yield content
                if data.get("done"):
                    usage.update(usage_from(data))
                    return
            raise LLMUnavailable("bad_stream")  # ended without its last line
        except httpx2.HTTPError:
            raise LLMUnavailable("stream_broken") from None
        finally:
            # Shielded: when the client goes away the task is cancelled, and an unshielded
            # await here would be cancelled too, leaving the model generating.
            with anyio.CancelScope(shield=True):
                await response.aclose()

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
