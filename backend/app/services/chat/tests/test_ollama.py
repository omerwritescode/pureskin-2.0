"""The Ollama client against a mock server (httpx2.MockTransport): loopback only, cloud
tags refused, the digest pinned, every status reason, the status probe never loading the
model, the stream's request (think off, the pinned options), thinking dropped, the counts,
broken streams, and the upstream stream closed when the reader stops."""

import asyncio
import re

import httpx2
import pytest

from app.services.chat import chat_config as cfg
from app.services.chat.llm import LLMUnavailable
from app.services.chat.ollama import OllamaClient, is_cloud_tag, loopback_url
from app.services.chat.tests.mock_ollama import (
    DIGEST,
    DONE,
    OTHER_DIGEST,
    TAG,
    MockOllama,
    piece,
    tag_entry,
)


@pytest.fixture(autouse=True)
def pinned(monkeypatch):
    monkeypatch.setattr(cfg, "ALLOWED_MODELS", {TAG: DIGEST, "remote-model:120b": DIGEST})


def client(mock: MockOllama, host: str | None = "http://127.0.0.1:11434", model: str | None = TAG) -> OllamaClient:
    return OllamaClient(host, model, transport=mock.transport())


def run(coro):
    return asyncio.run(coro)


def status_of(mock: MockOllama, with_version: bool = False, **kwargs):
    async def go():
        llm = client(mock, **kwargs)
        try:
            return await llm.status(with_version=with_version)
        finally:
            await llm.aclose()
    return run(go())


def check(mock: MockOllama):
    async def go():
        llm = client(mock)
        try:
            await llm.check_available()
        finally:
            await llm.aclose()
    return run(go())


async def drain(llm: OllamaClient, usage: dict | None = None, messages=None) -> list[str]:
    try:
        return [p async for p in llm.stream_chat(messages or [{"role": "user", "content": "q"}],
                                                 dict(cfg.MODEL_OPTIONS), usage)]
    finally:
        await llm.aclose()


# --- The host ------------------------------------------------------------------------------
@pytest.mark.parametrize(("host", "url"), [
    (None, "http://127.0.0.1:11434"),
    ("", "http://127.0.0.1:11434"),
    ("127.0.0.1", "http://127.0.0.1:11434"),
    ("127.0.0.1:11500", "http://127.0.0.1:11500"),
    ("http://localhost:11434", "http://127.0.0.1:11434"),
    ("localhost", "http://127.0.0.1:11434"),
    ("[::1]:11434", "http://[::1]:11434"),
    ("http://127.0.0.2:11434/", "http://127.0.0.2:11434"),
])
def test_loopback_hosts_are_accepted(host, url):
    assert loopback_url(host) == url


@pytest.mark.parametrize("host", [
    "0.0.0.0", "0.0.0.0:11434", "http://192.168.1.20:11434", "10.0.0.5", "http://example.com:11434",
    "ollama.local", "http://localhost.example.com", "ftp://127.0.0.1", "http://user:pw@127.0.0.1:11434",
    "http://127.0.0.1:11434/api", "http://127.0.0.1:99999", "http://[::]:11434", "https://ollama.com",
])
def test_anything_else_is_refused(host):
    assert loopback_url(host) is None


def test_a_non_loopback_host_never_gets_a_request():
    mock = MockOllama()
    llm = client(mock, host="http://192.168.1.20:11434")
    status = status_of(mock, with_version=True, host="http://192.168.1.20:11434")
    assert (status.available, status.reason) == (False, "non_loopback_host")
    with pytest.raises(LLMUnavailable, match="non_loopback_host"):
        run(drain(llm))
    assert mock.requests == []


def test_proxy_variables_and_redirects_are_ignored(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example.com:3128")
    llm = OllamaClient("127.0.0.1", TAG)
    assert llm._client.trust_env is False and llm._client.follow_redirects is False
    run(llm.aclose())


# --- The model -----------------------------------------------------------------------------
@pytest.mark.parametrize(("tag", "cloud"), [
    ("gpt-oss:120b-cloud", True), ("glm-4.6:cloud", True), ("Qwen3-Coder:480B-Cloud", True),
    ("qwen3.5:4b-q4_K_M", False), ("granite4.2:8b-q4_K_M", False), ("cloudy:7b", False),
])
def test_cloud_tags(tag, cloud):
    assert is_cloud_tag(tag) is cloud


def test_the_shipped_pins_are_full_digests_and_local(monkeypatch):
    monkeypatch.undo()  # the real chat_config, not this file's fixture
    for tag, digest in cfg.ALLOWED_MODELS.items():
        assert not is_cloud_tag(tag) and re.fullmatch(r"[0-9a-f]{64}", digest), tag


@pytest.mark.parametrize(("model", "reason"), [
    ("gpt-oss:120b-cloud", "cloud_tag"),
    ("", "unpinned_model"),
    (None, "unpinned_model"),
    ("unpinned:7b", "unpinned_model"),
])
def test_static_reasons_make_no_request(model, reason):
    mock = MockOllama()
    status = status_of(mock, with_version=True, model=model)
    assert (status.available, status.reason) == (False, reason)
    assert status.detail == cfg.STATUS_REASONS[reason]
    assert mock.requests == []


@pytest.mark.parametrize(("mock", "reason"), [
    (MockOllama(fail=httpx2.ConnectError("refused")), "unreachable"),
    (MockOllama(fail=httpx2.ConnectTimeout("slow")), "unreachable"),
    (MockOllama(tags_status=500), "unreachable"),
    (MockOllama(tags_body=b"<html>not ollama</html>"), "unreachable"),
    (MockOllama(tags_body=b"[1, 2]"), "unreachable"),
    (MockOllama(models=[]), "missing_model"),
    (MockOllama(models=[tag_entry("other:7b")]), "missing_model"),
    (MockOllama(models=[tag_entry(digest=OTHER_DIGEST)]), "moved_tag"),
    (MockOllama(models=[tag_entry(digest="")]), "moved_tag"),
    (MockOllama(models=[tag_entry(remote_host="https://ollama.com:443", remote_model="x")]), "cloud_tag"),
])
def test_status_reasons_from_ollama(mock, reason):
    status = status_of(mock)
    assert (status.available, status.reason, status.model, status.digest) == (False, reason, TAG, DIGEST)
    with pytest.raises(LLMUnavailable, match=reason):
        check(mock)


def test_available_with_the_pinned_digest():
    for digest in (DIGEST, f"sha256:{DIGEST}", DIGEST.upper()):
        status = status_of(MockOllama(models=[tag_entry("other:1b"), tag_entry(digest=digest)]), with_version=True)
        assert (status.available, status.reason, status.ollama_version) == (True, None, "0.35.1")
        assert status.detail == cfg.AVAILABLE_TEXT


def test_the_status_never_loads_the_model_and_times_out_in_one_second():
    mock = MockOllama()
    status_of(mock, with_version=True)
    check(mock)
    assert mock.paths == ["/api/version", "/api/tags", "/api/tags"]
    assert all(r["method"] == "GET" for r in mock.requests)
    for r in mock.requests:
        assert set(r["timeout"].values()) == {cfg.PROBE_TIMEOUT_SECONDS}


# --- The stream ------------------------------------------------------------------------------
def test_the_request_pins_the_model_options_and_turns_thinking_off():
    mock = MockOllama()
    messages = [{"role": "system", "content": "rules"}, {"role": "user", "content": "q"}]
    run(drain(client(mock), messages=messages))
    (request,) = mock.requests
    assert (request["method"], request["url"]) == ("POST", "http://127.0.0.1:11434/api/chat")
    assert request["body"] == {"model": TAG, "messages": messages, "stream": True, "think": False,
                               "options": cfg.MODEL_OPTIONS}
    assert request["timeout"]["read"] == cfg.READ_TIMEOUT_SECONDS
    assert request["timeout"]["connect"] == cfg.CONNECT_TIMEOUT_SECONDS


def test_pieces_are_passed_on_thinking_is_dropped_and_counted_and_usage_is_filled():
    mock = MockOllama(chat_lines=[piece("", thinking="secret plan"), piece("Reapply ", thinking="more"),
                                  "", piece("every two hours."), DONE])
    usage = {}
    assert run(drain(client(mock), usage)) == ["Reapply ", "every two hours."]
    assert usage == {"thinking": 2, "done_reason": "stop", "prompt_tokens": 812, "output_tokens": 42,
                     "load_ms": 5, "prompt_ms": 300, "eval_ms": 1500, "total_ms": 2000}
    assert mock.streams[0].closed


@pytest.mark.parametrize(("mock", "reason"), [
    (MockOllama(chat_status=404, chat_lines=[{"error": "model not found"}]), "model_error"),
    (MockOllama(chat_status=500, chat_lines=[{"error": "out of memory"}]), "model_error"),
    (MockOllama(chat_lines=[piece("Half a "), {"error": "runner crashed"}]), "model_error"),
    (MockOllama(chat_lines=[piece("Half a "), "{not json"]), "bad_stream"),
    (MockOllama(chat_lines=[piece("Half a "), "[1, 2]"]), "model_error"),
    (MockOllama(chat_lines=[piece("Never finished. ")]), "bad_stream"),
    (MockOllama(fail=httpx2.ConnectError("refused")), "unreachable"),
])
def test_a_broken_stream_is_llm_unavailable_and_still_closed(mock, reason):
    with pytest.raises(LLMUnavailable, match=reason):
        run(drain(client(mock)))
    assert all(s.closed for s in mock.streams)


def test_a_read_error_mid_stream_is_stream_broken():
    class Broken(MockOllama):
        def handler(self, request):
            response = super().handler(request)
            if request.url.path == "/api/chat":
                async def lines():
                    yield b'{"message": {"content": "Half "}, "done": false}\n'
                    raise httpx2.ReadError("connection reset")
                return httpx2.Response(200, content=lines())
            return response

    with pytest.raises(LLMUnavailable, match="stream_broken"):
        run(drain(client(Broken())))


def test_stopping_early_closes_the_upstream_stream():
    mock = MockOllama(chat_lines=[piece(f"word{i} ") for i in range(1000)] + [DONE], delay=0.001)

    async def first_two():
        llm = client(mock)
        stream = llm.stream_chat([{"role": "user", "content": "q"}], dict(cfg.MODEL_OPTIONS))
        got = [await anext(stream), await anext(stream)]
        await stream.aclose()  # what the gate stopping, or the client going away, does
        await llm.aclose()
        return got

    assert run(first_two()) == ["word0 ", "word1 "]
    (stream,) = mock.streams
    assert stream.closed and stream.sent < 10


def test_a_cancelled_reader_still_closes_the_upstream_stream():
    """The client going away cancels the task mid-read: the close is shielded."""
    mock = MockOllama(chat_lines=[piece("word ")] + [piece("x ")] * 1000 + [DONE], delay=0.05)

    async def cancelled():
        llm = client(mock)

        async def read():
            async for _ in llm.stream_chat([{"role": "user", "content": "q"}], dict(cfg.MODEL_OPTIONS)):
                pass

        task = asyncio.create_task(read())
        await asyncio.sleep(0.12)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await llm.aclose()

    run(cancelled())
    assert mock.streams[0].closed
