"""POST /api/chat and GET /api/chat/status through the real app (7d, Unit 3), with the fake
model or the real Ollama client on a mock server. No database (the user and the profile are
injected; test_chat_api_db.py covers real sign-in) and no Ollama.

Every status code; the NDJSON events; templates served with Ollama down; the limits (429
and the one-generation 503 across real concurrent requests; templates past the model's
limits, with their own); the client going away closing
the model's stream; the startup probe; and one metadata-only log line on every path.
"""

import asyncio
import json
import logging
import re
from types import SimpleNamespace

import httpx2
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.api import chat as chat_api
from app.api.deps import get_current_user, get_db
from app.main import app
from app.services.chat import chat_config as cfg
from app.services.chat.limits import ChatLimits
from app.services.chat.ollama import OllamaClient
from app.services.chat.tests.fakes import FakeLLM
from app.services.chat.tests.mock_ollama import DIGEST, DONE, OTHER_DIGEST, TAG, MockOllama, piece, tag_entry
from app.services.chat.tests.test_context import context_for, sentinel_profile

PROFILE, _ = context_for(sentinel_profile())
USER_ID = 987654321
IN_KB = "How often should I reapply sunscreen during the day?"
RED_FLAG = "my lips are swelling after the new cream"
OFF_TOPIC = "What's a quick recipe for dinner tonight?"
ANSWER = ["Reapply at least every two hours [kb-sun-sunscreen-use]. ", "Your sunscreen step covers it [profile]."]


class FakeDB:
    closed = False

    def close(self):
        self.closed = True


class Harness:
    def __init__(self):
        self.user = SimpleNamespace(id=USER_ID)
        self.db = FakeDB()
        self.llm = FakeLLM(ANSWER)
        self.limits = ChatLimits()
        self.profile = PROFILE
        self.loaded = 0

    def load_profile(self, db, user):
        self.loaded += 1
        assert db is self.db and user is self.user
        return self.profile


@pytest.fixture
def h():
    harness = Harness()

    def fake_db():
        yield harness.db

    overrides = {
        get_current_user: lambda: harness.user,
        get_db: fake_db,
        chat_api.get_chat_llm: lambda: harness.llm,
        chat_api.get_chat_limits: lambda: harness.limits,
        chat_api.get_profile_loader: lambda: harness.load_profile,
    }
    app.dependency_overrides.update(overrides)
    yield harness
    for key in overrides:
        app.dependency_overrides.pop(key, None)


@pytest.fixture
def client():
    return TestClient(app)  # no `with`: no startup (image model, chat probe) needed here


def ollama(monkeypatch, mock: MockOllama, host: str = "127.0.0.1", model: str = TAG) -> OllamaClient:
    monkeypatch.setattr(cfg, "ALLOWED_MODELS", {TAG: DIGEST})
    return OllamaClient(host, model, transport=mock.transport())


def post(client, message=IN_KB, history=(), **kwargs):
    return client.post("/api/chat", json={"message": message, "history": list(history)}, **kwargs)


def events(response) -> list[dict]:
    assert response.headers["content-type"].startswith("application/x-ndjson")
    return [json.loads(line) for line in response.text.splitlines()]


def texts(evs) -> list[str]:
    return [e["text"] for e in evs if e["type"] == "text"]


# --- 200 ----------------------------------------------------------------------------------
def test_an_answer_streams_as_ndjson_events(h, client):
    response = post(client)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    evs = events(response)
    start = evs[0]
    assert start["type"] == "start" and start["route"] == "model"
    assert re.fullmatch(r"[0-9a-f]{12}", start["request_id"])
    assert start["config_versions"] == {"chat": cfg.CHAT_CONFIG_VERSION, "kb": chat_api.knowledge()[0].version,
                                        "model": FakeLLM.model, "model_digest": None}
    assert texts(evs) == ["Reapply at least every two hours.", "Your sunscreen step covers it."]
    assert evs[1]["cites"] == ["kb-sun-sunscreen-use"] and evs[2]["cites"] == ["profile"]
    citations = next(e for e in evs if e["type"] == "citations")
    assert [c["id"] for c in citations["chunks"]] == ["kb-sun-sunscreen-use"]
    assert evs[-1] == {"type": "end", "reason": "answered"}
    assert h.llm.options == [cfg.MODEL_OPTIONS] and h.llm.closed
    assert h.loaded == 1 and h.db.closed  # no database connection held while streaming
    assert h.limits.slot.in_use == 0


def test_the_history_reaches_the_model_and_the_router(h, client):
    history = [{"role": "user", "content": "I have oily skin"}, {"role": "assistant", "content": "Noted."}]
    assert post(client, history=history).status_code == 200
    sent = h.llm.calls[0]
    assert [m["role"] for m in sent] == ["system", "system", "user", "assistant", "user"]
    assert sent[2]["content"] == "I have oily skin" and sent[3]["content"] == "Noted."

    h.llm = FakeLLM(["never"], available=False)
    pregnant = [{"role": "user", "content": "I'm pregnant"}, {"role": "assistant", "content": "Noted."}]
    evs = events(post(client, "and I use retinol, which sunscreen?", pregnant))
    assert evs[0]["route"] == "template" and h.llm.calls == []
    assert " ".join(texts(evs)) == cfg.TEMPLATES["pregnancy_retinoid"]["text"]


def test_a_red_flag_template_is_served_with_ollama_down(h, client):
    h.llm = FakeLLM(["never"], available=False)
    response = post(client, RED_FLAG)
    assert response.status_code == 200
    evs = events(response)
    assert evs[0]["route"] == "template" and evs[-1] == {"type": "end", "reason": "template"}
    assert " ".join(texts(evs)) == cfg.TEMPLATES["emergency_allergy"]["text"]
    assert h.llm.calls == [] and h.llm.availability_checks == 0


def test_the_fixed_no_answer_needs_no_model_call(h, client):
    evs = events(post(client, OFF_TOPIC))
    assert evs[0]["route"] == "no_answer" and " ".join(texts(evs)) == cfg.NO_ANSWER_TEXT
    assert evs[-1]["reason"] == "no_answer_line" and h.llm.calls == []


def test_a_caution_line_comes_after_the_answer(h, client):
    h.llm = FakeLLM(["[NO_ANSWER]"])
    evs = events(post(client, "Can I use retinol on a mole?"))
    cautions = [e for e in evs if e["type"] == "caution"]
    assert [c["text"] for c in cautions] == [cfg.CAUTIONS["mole"]["text"]]
    assert evs.index(cautions[0]) > max(i for i, e in enumerate(evs) if e["type"] == "text")


def test_a_model_failure_after_the_start_is_an_error_event(h, client):
    h.llm = FakeLLM(["Reapply every two hours [kb-sun-sunscreen-use]. ", "more"], fail_after=1)
    response = post(client)
    assert response.status_code == 200
    evs = events(response)
    assert texts(evs) == []  # F1: nothing is released before the stream ends
    assert evs[-1] == {"type": "error", "code": "stream_broken"}
    assert not any(e["type"] == "end" for e in evs) and h.limits.slot.in_use == 0


def test_a_sentence_cut_off_by_the_token_limit_is_not_sent(h, client):
    h.llm = FakeLLM(["Reapply every two hours [kb-sun-sunscreen-use]. ", "And after swimming you should"],
                    done_reason="length")
    assert texts(events(post(client))) == ["Reapply every two hours."]


# --- 401, 413, 422 ------------------------------------------------------------------------------
def test_401_before_anything_is_read(h, client):
    del app.dependency_overrides[get_current_user]
    assert post(client).status_code == 401
    assert post(client, headers={"Authorization": "Bearer not-a-token"}).status_code == 401
    big = client.post("/api/chat", content=b"x" * (cfg.MAX_BODY_BYTES * 2))
    assert big.status_code == 401
    assert h.llm.calls == [] and h.loaded == 0
    assert client.get("/api/chat/status").status_code == 401


def test_413_over_16_kb(h, client):
    body = json.dumps({"message": "x", "history": [{"role": "assistant", "content": "y" * 2999}] * 6}).encode()
    assert len(body) > cfg.MAX_BODY_BYTES
    for response in (client.post("/api/chat", content=body, headers={"content-type": "application/json"}),
                     client.post("/api/chat", content=iter([body[:9000], body[9000:]]))):  # chunked: no length
        assert response.status_code == 413
        assert response.json() == {"detail": chat_api.TOO_LARGE}
    assert h.loaded == 0 and h.llm.calls == []


def test_16_kb_is_enough_for_three_full_exchanges(h, client):
    history = [{"role": "user", "content": "u" * cfg.MAX_MESSAGE_CHARS},
               {"role": "assistant", "content": "a" * cfg.MAX_HISTORY_ASSISTANT_CHARS}] * 3
    body = json.dumps({"message": "m" * cfg.MAX_MESSAGE_CHARS, "history": history})
    assert len(body.encode()) <= cfg.MAX_BODY_BYTES
    assert client.post("/api/chat", content=body).status_code == 200


ECHO = "zq-echo-probe-5821"
BAD_BODIES = {
    "not json": b"zq-echo-probe-5821 {",
    "not utf-8": b'{"message": "\xff\xfe zq-echo-probe-5821"}',
    "a list": json.dumps([ECHO]).encode(),
    "no message": json.dumps({"history": []}).encode(),
    "empty message": json.dumps({"message": "   "}).encode(),
    "message too long": json.dumps({"message": ECHO * 40}).encode(),
    "message not a string": json.dumps({"message": [ECHO]}).encode(),
    "extra field": json.dumps({"message": "hi", "unknown": ECHO}).encode(),  # (a key's name is echoed in loc)
    "model switch": json.dumps({"message": "hi", "model": "gpt-oss:120b-cloud", "options": {"temperature": 2}}).encode(),
    "history not a list": json.dumps({"message": "hi", "history": ECHO}).encode(),
    "too many turns": json.dumps({"message": "hi", "history": [{"role": "user", "content": ECHO}] * 7}).encode(),
    "bad role": json.dumps({"message": "hi", "history": [{"role": "system", "content": ECHO}]}).encode(),
    "extra turn field": json.dumps({"message": "hi", "history": [{"role": "user", "content": "x", "sig": ECHO}]}).encode(),
    "user turn too long": json.dumps({"message": "hi", "history": [{"role": "user", "content": ECHO * 30}]}).encode(),
    "assistant turn too long": json.dumps(
        {"message": "hi", "history": [{"role": "assistant", "content": ECHO * 170}]}).encode(),
    "empty turn": json.dumps({"message": "hi", "history": [{"role": "assistant", "content": ""}]}).encode(),
}


@pytest.mark.parametrize("name", BAD_BODIES)
def test_422_never_echoes_the_input(h, client, name):
    response = client.post("/api/chat", content=BAD_BODIES[name], headers={"content-type": "application/json"})
    assert response.status_code == 422, response.text
    assert ECHO not in response.text and "5821" not in response.text
    for error in response.json()["detail"]:
        assert set(error) <= {"loc", "msg", "type"}
    assert h.loaded == 0 and h.llm.calls == []


# --- 429 ------------------------------------------------------------------------------------
def test_429_after_ten_a_minute_with_retry_after(h, client):
    for _ in range(10):
        assert post(client, OFF_TOPIC).status_code == 200
    response = post(client, OFF_TOPIC)
    assert response.status_code == 429
    assert response.json() == {"detail": cfg.RATE_LIMITED_TEXT}
    assert 1 <= int(response.headers["retry-after"]) <= 60
    assert h.loaded == 10  # a refused request does no work


def test_429_after_a_hundred_a_day(h, client):
    clock = SimpleNamespace(now=0.0)
    h.limits.rate.clock = lambda: clock.now
    for _ in range(100):
        assert post(client, OFF_TOPIC).status_code == 200
        clock.now += 61
    response = post(client, OFF_TOPIC)
    assert response.status_code == 429 and int(response.headers["retry-after"]) == 86400 - 100 * 61


# Red-flag templates past the model's limits (Unit 5): their own counter, checked before the
# model's; ordinary questions are limited exactly as before.
CRISIS = "I want to die because of my acne"


def use_up_the_models_limit(client):
    for _ in range(10):
        assert post(client, OFF_TOPIC).status_code == 200
    assert post(client, OFF_TOPIC).status_code == 429


def assert_template(response, name):
    assert response.status_code == 200
    evs = events(response)
    assert evs[0]["route"] == "template" and evs[-1] == {"type": "end", "reason": "template"}
    assert " ".join(texts(evs)) == cfg.TEMPLATES[name]["text"]


def test_a_crisis_message_after_ten_a_minute_still_gets_its_template(h, client):
    use_up_the_models_limit(client)
    assert_template(post(client, CRISIS), "crisis")
    assert_template(post(client, RED_FLAG), "emergency_allergy")
    assert h.llm.calls == [] and h.loaded == 10  # a template never reads the profile
    assert post(client, OFF_TOPIC).status_code == 429  # ordinary questions are still limited


def test_a_red_flag_after_a_hundred_a_day_still_gets_its_template(h, client):
    clock = SimpleNamespace(now=0.0)
    h.limits.rate.clock = h.limits.template_rate.clock = lambda: clock.now
    for _ in range(100):
        assert post(client, OFF_TOPIC).status_code == 200
        clock.now += 61
    assert post(client, OFF_TOPIC).status_code == 429
    assert_template(post(client, CRISIS), "crisis")


def test_a_red_flag_in_the_history_still_gets_its_template_after_the_limit(h, client):
    use_up_the_models_limit(client)
    history = [{"role": "user", "content": "I've been thinking about suicide"}, {"role": "assistant", "content": "Noted."}]
    assert_template(post(client, "Which sunscreen should I buy?", history), "crisis")
    assert post(client, "Which sunscreen should I buy?").status_code == 429


def test_templates_have_their_own_limit_and_never_use_the_models(h, client):
    for _ in range(30):
        assert_template(post(client, RED_FLAG), "emergency_allergy")
    response = post(client, RED_FLAG)
    assert response.status_code == 429 and response.json() == {"detail": cfg.RATE_LIMITED_TEXT}
    assert 1 <= int(response.headers["retry-after"]) <= 60
    assert h.loaded == 0 and h.llm.calls == []
    for _ in range(10):  # all ten of the model's minute are still there
        assert post(client).status_code == 200
    assert post(client).status_code == 429


def test_busy_and_over_the_limit_a_red_flag_still_gets_its_template(h, client):
    use_up_the_models_limit(client)
    assert h.limits.slot.try_acquire()  # another answer is being generated
    assert_template(post(client, CRISIS), "crisis")
    assert post(client).status_code == 429  # an ordinary question: the limit comes before busy, as before
    h.limits.slot.release()


def test_with_ollama_down_and_over_the_limit_a_red_flag_still_gets_its_template(h, client):
    use_up_the_models_limit(client)
    h.llm = FakeLLM(available=False)
    assert_template(post(client, CRISIS), "crisis")
    assert post(client).status_code == 429  # an ordinary question: still the 429, not the 503
    assert h.llm.availability_checks == 0


def spy(limiter) -> list:
    """Records every key the limiter is asked to count, whether or not it allows it."""
    calls, real = [], limiter.hit

    def hit(key):
        calls.append(key)
        return real(key)

    limiter.hit = hit
    return calls


MOLE = "my mole is itchy and changing colour"


def exchanges(*user_turns: str) -> list[dict]:
    return [m for t in user_turns for m in ({"role": "user", "content": t}, {"role": "assistant", "content": "Noted."})]


# The oldest user turn of three exchanges (the most the API takes), the message, and what both
# the endpoint's limit and the pipeline's route must make of them.
ROUTE_PARITY = {
    "self-harm in the oldest turn": ("I've been thinking about suicide", "Which sunscreen should I buy?", True),
    "pregnancy in the oldest turn, retinol now": ("I'm pregnant", "Can I keep using my retinol serum?", True),
    "a mole in the oldest turn (a caution line only)": (MOLE, "Which sunscreen should I buy?", False),
    "nothing": ("I have oily skin", "Which sunscreen should I buy?", False),
}


@pytest.mark.parametrize("case", ROUTE_PARITY)
def test_the_endpoint_and_the_pipeline_make_the_same_template_decision(h, client, case):
    oldest, message, template = ROUTE_PARITY[case]
    model_counted, template_counted = spy(h.limits.rate), spy(h.limits.template_rate)
    evs = events(post(client, message, exchanges(oldest, "ok", "thanks")))
    assert len(model_counted) + len(template_counted) == 1
    assert bool(template_counted) == (evs[0]["route"] == "template") == template
    cautions = [e["text"] for e in evs if e["type"] == "caution"]
    assert cautions == ([cfg.CAUTIONS["mole"]["text"]] if oldest == MOLE else [])  # the oldest turn was read


def test_more_than_three_exchanges_is_refused_before_anything_routes_or_counts(h, client):
    model_counted, template_counted = spy(h.limits.rate), spy(h.limits.template_rate)
    history = exchanges("I've been thinking about suicide", "ok", "thanks", "and another")  # the flag only in the oldest
    assert post(client, "Which sunscreen should I buy?", history).status_code == 422
    assert model_counted == template_counted == [] and h.loaded == 0 and h.llm.calls == []


def test_a_non_template_message_never_counts_toward_the_templates_limit(h, client):
    model_counted, template_counted = spy(h.limits.rate), spy(h.limits.template_rate)
    assert client.post("/api/chat", content=b"{").status_code == 422  # not counted at all
    assert events(post(client))[0]["route"] == "model"
    assert events(post(client, OFF_TOPIC))[0]["route"] == "no_answer"
    soft = events(post(client, "My retinol serum stings a little after I put it on"))
    assert soft[0]["route"] != "template" and any(e["type"] == "caution" for e in soft)  # a soft flag
    mole = events(post(client, "Which sunscreen should I buy?", exchanges(MOLE)))
    assert mole[0]["route"] != "template" and any(e["type"] == "caution" for e in mole)  # a flag in history only
    assert h.limits.slot.try_acquire()
    assert post(client).status_code == 503  # busy
    h.limits.slot.release()
    h.llm = FakeLLM(available=False)
    for _ in range(5):
        assert post(client).status_code == 503  # unavailable
    assert post(client).status_code == 429  # the eleventh: over the model's limit
    assert template_counted == [] and len(model_counted) == 11


# --- 503 ------------------------------------------------------------------------------------
UNAVAILABLE = {
    "unreachable": dict(mock=MockOllama(fail=httpx2.ConnectError("refused"))),
    "missing_model": dict(mock=MockOllama(models=[tag_entry("other:7b")])),
    "moved_tag": dict(mock=MockOllama(models=[tag_entry(digest=OTHER_DIGEST)])),
    "cloud_tag": dict(mock=MockOllama(), model="gpt-oss:120b-cloud"),
    "non_loopback_host": dict(mock=MockOllama(), host="http://192.168.1.20:11434"),
    "unpinned_model": dict(mock=MockOllama(), model="unpinned:7b"),
}


@pytest.mark.parametrize("reason", UNAVAILABLE)
def test_503_with_the_reason_and_no_text(h, client, monkeypatch, reason):
    case = UNAVAILABLE[reason]
    mock = case["mock"]
    mock.requests.clear()
    h.llm = ollama(monkeypatch, mock, host=case.get("host", "127.0.0.1"), model=case.get("model", TAG))
    response = post(client)
    assert response.status_code == 503
    assert response.json() == {"detail": cfg.STATUS_REASONS[reason], "reason": reason}
    assert "retry-after" not in response.headers
    assert "/api/chat" not in mock.paths  # never a model call
    status = client.get("/api/chat/status").json()
    assert status == {"available": False, "reason": reason, "detail": cfg.STATUS_REASONS[reason],
                      "model": case.get("model", TAG)}
    # A red flag is still answered.
    assert post(client, RED_FLAG).status_code == 200
    asyncio.run(h.llm.aclose())


def test_the_status_when_available(h, client, monkeypatch):
    mock = MockOllama()
    h.llm = ollama(monkeypatch, mock)
    assert client.get("/api/chat/status").json() == {"available": True, "reason": None,
                                                    "detail": cfg.AVAILABLE_TEXT, "model": TAG}
    assert mock.paths == ["/api/tags"]


def test_503_busy_with_retry_after_while_templates_and_no_answer_are_still_served(h, client):
    assert h.limits.slot.try_acquire()  # another answer is being generated
    response = post(client)
    assert response.status_code == 503
    assert response.json() == {"detail": cfg.BUSY_TEXT, "reason": "busy"}
    assert response.headers["retry-after"] == str(cfg.BUSY_RETRY_AFTER_SECONDS)
    assert h.llm.calls == []
    assert events(post(client, RED_FLAG))[0]["route"] == "template"
    assert events(post(client, OFF_TOPIC))[0]["route"] == "no_answer"
    h.limits.slot.release()
    assert post(client).status_code == 200


def test_one_generation_at_a_time_across_real_concurrent_requests(h):
    release = asyncio.Event()

    async def scenario():
        h.llm = FakeLLM(ANSWER, gate=release)
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://test") as ac:
            first = asyncio.create_task(ac.post("/api/chat", json={"message": IN_KB}))
            await asyncio.wait_for(_until(lambda: h.limits.slot.in_use == 1), 5)
            busy = await ac.post("/api/chat", json={"message": IN_KB})
            template = await ac.post("/api/chat", json={"message": RED_FLAG})
            release.set()
            done = await asyncio.wait_for(first, 5)
            after = await ac.post("/api/chat", json={"message": IN_KB})
        return busy, template, done, after

    busy, template, done, after = asyncio.run(scenario())
    assert (busy.status_code, busy.json()["reason"]) == (503, "busy")
    assert template.status_code == 200 and done.status_code == 200 and after.status_code == 200
    assert texts(events(done)) == texts(events(after)) == ["Reapply at least every two hours.",
                                                           "Your sunscreen step covers it."]
    assert h.limits.slot.in_use == 0


async def _until(condition):
    while not condition():
        await asyncio.sleep(0.005)


# --- The client going away ---------------------------------------------------------------
def _scope(body: bytes) -> dict:
    return {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1",
            "method": "POST", "scheme": "http", "path": "/api/chat", "raw_path": b"/api/chat", "query_string": b"",
            "root_path": "", "client": ("127.0.0.1", 50000), "server": ("testserver", 80), "state": {},
            "headers": [(b"host", b"testserver"), (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode())]}


@pytest.mark.parametrize("gone_while", ["model_streaming", "sending_the_start"])
def test_the_client_going_away_closes_the_models_stream_and_frees_the_slot(h, monkeypatch, caplog, gone_while):
    """Driven at the ASGI level as uvicorn does it (ASGI 2.3: on http.disconnect Starlette
    cancels the body, but doesn't close it), against the real Ollama client. The client goes
    away either while the model is streaming (the answer is checked but not yet released:
    F1), or while the start line is being sent (the answer is then paused at a yield, holding
    the generation slot: only the explicit close reaches it). Checked the moment the response
    returns, so the garbage collector can't be what closed it."""
    caplog.set_level(logging.INFO)
    mock = MockOllama(chat_lines=[piece("Reapply every two hours [kb-sun-sunscreen-use]. ")]
                      + [piece("and ")] * 2000 + [DONE], delay=0.01)  # 20 s if never stopped
    h.llm = ollama(monkeypatch, mock)
    body = json.dumps({"message": IN_KB}).encode()
    sent: list[dict] = []

    async def scenario():
        started = asyncio.Event()
        delivered = False

        async def receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            if gone_while == "model_streaming":
                while not (mock.streams and mock.streams[0].sent >= 3):
                    await asyncio.sleep(0.005)
            else:
                await started.wait()
            return {"type": "http.disconnect"}  # the user pressed Stop / closed the tab

        async def send(message):
            sent.append(message)
            if message["type"] == "http.response.body" and b'"type": "start"' in message.get("body", b""):
                started.set()
                if gone_while == "sending_the_start":
                    await asyncio.sleep(1)  # a slow client: the disconnect arrives meanwhile

        await asyncio.wait_for(app(_scope(body), receive, send), 10)
        at_return = (all(s.closed for s in mock.streams), h.limits.slot.in_use)  # no await since it ended
        await h.llm.aclose()
        return at_return

    closed, in_use = asyncio.run(scenario())
    assert closed and in_use == 0
    if gone_while == "model_streaming":
        assert len(mock.streams) == 1 and 3 <= mock.streams[0].sent < 100
    else:
        assert mock.streams == []  # the model was never asked
    assert sent[0]["status"] == 200
    assert not any(b'"type": "text"' in m.get("body", b"") or b'"type": "end"' in m.get("body", b"") for m in sent)
    turns = [r.getMessage() for r in caplog.records if r.getMessage().startswith("chat turn:")]
    assert len(turns) == 1 and "outcome=stopped" in turns[0]


def test_closing_the_body_after_the_start_frees_the_slot_and_never_asks_the_model(h, monkeypatch):
    """The other way a response can end early: the body closed at a yield."""
    mock = MockOllama()
    h.llm = ollama(monkeypatch, mock)

    async def scenario():
        from starlette.requests import Request

        body = json.dumps({"message": IN_KB}).encode()

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        response = await chat_api.chat(Request(_scope(body), receive), user=h.user, db=h.db, llm=h.llm,
                                       limits=h.limits, load_profile=h.load_profile)
        lines = response.body_iterator
        first = await anext(lines)
        held = h.limits.slot.in_use
        await lines.aclose()
        await h.llm.aclose()
        return first, held

    first, held = asyncio.run(scenario())
    assert json.loads(first)["type"] == "start" and held == 1
    assert h.limits.slot.in_use == 0 and "/api/chat" not in mock.paths


# --- Startup ---------------------------------------------------------------------------------
def test_the_startup_probe_logs_one_line_and_never_loads_the_model(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    for mock, expected in ((MockOllama(), "Chat: available (test-model:4b-q4_K_M, digest 0f0f0f0f0f0f, Ollama 0.35.1)"),
                           (MockOllama(fail=httpx2.ConnectError("refused")),
                            f"Chat unavailable (unreachable): {cfg.STATUS_REASONS['unreachable']}")):
        caplog.clear()
        llm = ollama(monkeypatch, mock)
        asyncio.run(chat_api.probe_chat(llm))
        assert [r.getMessage() for r in caplog.records if r.name == "uvicorn.error"] == [expected]
        assert set(mock.paths) <= {"/api/version", "/api/tags"}
        assert all(set(r["timeout"].values()) == {cfg.PROBE_TIMEOUT_SECONDS} for r in mock.requests)
        asyncio.run(llm.aclose())


def test_startup_never_waits_for_ollama(monkeypatch):
    probe_started, probe_cancelled = asyncio.Event(), []

    async def never_answers():
        probe_started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            probe_cancelled.append(True)
            raise

    def no_face_model():
        raise main.image_analysis_service.ModelUnavailable("not needed here")

    monkeypatch.setattr(main.image_analysis_service, "load_models", no_face_model)
    monkeypatch.setattr(chat_api, "probe_chat", never_answers)

    async def scenario():
        async with asyncio.timeout(2):
            async with main.lifespan(app):
                await asyncio.wait_for(probe_started.wait(), 1)  # running, but nobody waits for it

    asyncio.run(scenario())
    assert probe_cancelled == [True]


# --- Logging: one metadata line per request, never text ------------------------------------
SENTINEL = "zqxj-sentinel-message"
SENTINEL_HISTORY = "zqxj-sentinel-history"
SENTINEL_ANSWER = "zqxj-sentinel-answer"
SECRETS = ("zqxj", "sentinel", "kb-", "swelling", "lips", "recipe", "reapply", "E1", "emergency_allergy",
           str(USER_ID), "FixtureBrand", "adenosine")


def _case(name, h, monkeypatch):
    """Sets the harness up for one path; returns (message, expected status, expected outcome)."""
    message = f"{SENTINEL} how often should I reapply sunscreen"
    if name == "template":
        return f"{SENTINEL} my lips are swelling", 200, "template"
    if name == "unavailable":
        h.llm = FakeLLM(available=False)
        return message, 503, "unavailable"
    if name == "line":
        return f"{SENTINEL} recipe", 200, "no_answer_line"
    if name == "ingredient":
        return f"{SENTINEL} does adenosine help with sunscreen and sun spots", 200, "no_answer_ingredient"
    if name == "coverage":
        monkeypatch.setattr(cfg, "TERM_COVERAGE_MIN", 0.99)
        return message, 200, "no_answer_coverage"
    if name == "context":
        monkeypatch.setattr(cfg, "MODEL_OPTIONS", {**cfg.MODEL_OPTIONS, "num_ctx": 400, "num_predict": 50})
        return message, 200, "no_answer_context"
    if name == "answered":
        h.llm = FakeLLM([f"{SENTINEL_ANSWER} reapply [kb-sun-sunscreen-use]. "])
        return message, 200, "answered"
    if name == "answered_ollama":
        h.llm = ollama(monkeypatch, MockOllama(chat_lines=[piece(f"{SENTINEL_ANSWER} reapply [kb-sun-sunscreen-use]. "),
                                                           DONE]))
        return message, 200, "answered"
    if name == "gate":
        h.llm = FakeLLM([f"{SENTINEL_ANSWER}. It cures acne."])
        return message, 200, "gate_claim"
    if name == "no_answer_model":
        h.llm = FakeLLM(["[NO_ANSWER]"])
        return message, 200, "no_answer_model"
    if name == "stream_error":
        h.llm = FakeLLM([f"{SENTINEL_ANSWER}. ", "more"], fail_after=1)
        return message, 200, "stream_error"
    if name == "busy":
        h.limits.slot.try_acquire()
        return message, 503, "busy"
    if name == "rate_limited":
        for _ in range(10):
            h.limits.rate.hit(USER_ID)
        return message, 429, "rate_limited"
    if name == "rate_limited_template":
        for _ in range(30):
            h.limits.template_rate.hit(USER_ID)
        return f"{SENTINEL} my lips are swelling", 429, "rate_limited_template"
    if name == "invalid":
        return message + "x" * cfg.MAX_MESSAGE_CHARS, 422, "invalid"
    if name == "too_large":
        return message + "x" * cfg.MAX_BODY_BYTES, 413, "too_large"
    raise AssertionError(name)


LOG_PATHS = ("template", "unavailable", "line", "coverage", "ingredient", "context", "answered", "answered_ollama", "gate",
             "no_answer_model", "stream_error", "busy", "rate_limited", "rate_limited_template", "invalid", "too_large")


@pytest.mark.parametrize("name", LOG_PATHS)
def test_one_log_line_per_request_and_never_any_text(h, client, monkeypatch, caplog, name):
    caplog.set_level(logging.DEBUG)
    message, status, outcome = _case(name, h, monkeypatch)
    history = [{"role": "user", "content": SENTINEL_HISTORY}, {"role": "assistant", "content": SENTINEL_HISTORY}]
    response = post(client, message, history)
    assert response.status_code == status
    lines = [r.getMessage() for r in caplog.records]
    turns = [line for line in lines if line.startswith("chat turn:")]
    assert len(turns) == 1, lines
    assert f"outcome={outcome} " in turns[0] + " " and re.search(r"request=[0-9a-f]{12} ", turns[0])
    for line in lines:
        for secret in SECRETS:
            assert secret not in line, (name, line)
    if isinstance(h.llm, OllamaClient):
        asyncio.run(h.llm.aclose())
