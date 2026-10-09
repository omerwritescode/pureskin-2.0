"""The pipeline, end to end with the fake model: red flags never reach the model (even with
Ollama down), fail-closed 503, the fixed "I don't know" paths, the gate on the model's
answer, caution lines, the citations' publishers, and logs without text."""

import logging

import pytest

from app.services.chat import chat_config as cfg
from app.services.chat.kb import load_kb
from app.services.chat.llm import LLMUnavailable
from app.services.chat.pipeline import respond
from app.services.chat.redflags import Turn, split_sentences
from app.services.chat.retrieval import build_index
from app.services.chat.tests.fakes import FakeLLM, collect
from app.services.chat.tests.test_context import context_for, sentinel_profile
from app.services.chat.tests.test_redflags import POSITIVE

KB = load_kb()
INDEX = build_index(KB)
PROFILE, _ = context_for(sentinel_profile())
PID = next(iter(PROFILE.products))
RED_FLAGS = [m for ms in POSITIVE.values() for m in ms]
IN_KB = "How often should I reapply sunscreen during the day?"


def run(message, llm, history=(), profile=PROFILE):
    return collect(respond(message, list(history), llm, kb=KB, index=INDEX, profile=profile))


def texts(events):
    return [e.data["text"] for e in events if e.type == "text"]


def end(events):
    return events[-1].data["reason"]


@pytest.mark.parametrize("message", RED_FLAGS)
def test_red_flags_never_reach_the_model_even_with_ollama_down(message):
    llm = FakeLLM(["should never be sent"], available=False)
    events = run(message, llm)
    assert llm.calls == [] and llm.availability_checks == 0
    assert events[0].data == {"route": "template"} and end(events) == "template"


def test_triggers_only_in_history_never_reach_the_model():
    llm = FakeLLM(["should never be sent"], available=False)
    history = [Turn("user", "I'm pregnant"), Turn("assistant", "Noted."), Turn("user", "and I use retinol")]
    events = run("what sunscreen should I use?", llm, history)
    assert llm.calls == [] and llm.availability_checks == 0
    assert " ".join(texts(events)) == cfg.TEMPLATES["pregnancy_retinoid"]["text"]


def test_the_template_is_sent_sentence_by_sentence_exactly():
    events = run("I found a new mole", FakeLLM(available=False))
    assert texts(events) == split_sentences(cfg.TEMPLATES["mole"]["text"])


def test_anything_else_needs_the_model_and_fails_closed_when_it_is_down():
    llm = FakeLLM(["never"], available=False, reason="unreachable")
    with pytest.raises(LLMUnavailable, match="unreachable"):
        run(IN_KB, llm)
    assert llm.availability_checks == 1 and llm.calls == []


def test_below_the_line_is_the_fixed_no_answer_without_a_model_call():
    llm = FakeLLM(["never"])
    events = run("What's a quick recipe for dinner tonight?", llm)
    assert llm.calls == [] and end(events) == "no_answer_line"
    assert " ".join(texts(events)) == cfg.NO_ANSWER_TEXT


def test_below_term_coverage_is_the_fixed_no_answer_without_a_model_call(monkeypatch):
    monkeypatch.setattr(cfg, "TERM_COVERAGE_MIN", 0.99)
    llm = FakeLLM(["never"])
    events = run(IN_KB, llm)
    assert llm.calls == [] and end(events) == "no_answer_coverage"


def test_a_context_that_cannot_fit_is_the_fixed_no_answer_without_a_model_call(monkeypatch):
    monkeypatch.setattr(cfg, "MODEL_OPTIONS", {**cfg.MODEL_OPTIONS, "num_ctx": 400, "num_predict": 50})
    llm = FakeLLM(["never"])
    events = run(IN_KB, llm)
    assert llm.calls == [] and end(events) == "no_answer_context"
    assert " ".join(texts(events)) == cfg.NO_ANSWER_TEXT


def test_a_gated_answer_with_names_swapped_in_and_publishers_on_citations():
    llm = FakeLLM(["Reapply at least every two hours [kb-sun-sunscreen-use]. ",
                   f"Your routine's sunscreen step uses [P{PID}] [profile].", " Invented [kb-made-up]."])
    events = run(IN_KB, llm)
    assert texts(events)[0] == "Reapply at least every two hours."
    assert PROFILE.products[PID] in texts(events)[1] and "[P" not in " ".join(texts(events))
    cites = next(e for e in events if e.type == "citations").data["chunks"]
    assert [c["id"] for c in cites] == ["kb-sun-sunscreen-use"]
    assert all(s["publisher"] for s in cites[0]["sources"])
    assert end(events) == "answered" and llm.closed


def test_the_gate_stops_the_model_and_closes_its_stream():
    llm = FakeLLM(["A fine sentence [kb-sun-sunscreen-use]. ", "This cures acne. ", "never ", "sent."])
    events = run(IN_KB, llm)
    assert texts(events) == ["A fine sentence.", *split_sentences(cfg.GATE_STOP_TEXT)]
    assert end(events) == "gate_claim" and llm.closed


def test_the_models_no_answer_becomes_the_fixed_reply():
    events = run(IN_KB, FakeLLM(["[NO_ANSWER]"]))
    assert " ".join(texts(events)) == cfg.NO_ANSWER_TEXT and end(events) == "no_answer_model"


def test_thinking_never_goes_out():
    events = run(IN_KB, FakeLLM(["<think>private reasoning</think>", "Reapply every two hours [kb-sun-sunscreen-use]."]))
    assert all("private" not in t for t in texts(events))


def test_caution_lines_come_after_the_answer():
    events = run("Can I use retinol on a mole?", FakeLLM(["[NO_ANSWER]"]))
    cautions = [e.data["text"] for e in events if e.type == "caution"]
    assert cautions == [cfg.CAUTIONS["mole"]["text"]]
    assert events.index(next(e for e in events if e.type == "caution")) > max(
        i for i, e in enumerate(events) if e.type == "text")


def test_a_history_only_match_becomes_a_caution_line():
    llm = FakeLLM(["Reapply every two hours [kb-sun-sunscreen-use]."])
    events = run(IN_KB, llm, [Turn("user", "my mole is bleeding")])
    assert llm.calls and [e.data["text"] for e in events if e.type == "caution"] == [cfg.CAUTIONS["mole"]["text"]]


def test_no_profile_is_general_answers():
    llm = FakeLLM(["Reapply every two hours [kb-sun-sunscreen-use]."])
    run(IN_KB, llm, profile=None)
    assert llm.calls[0][1]["content"] == cfg.NO_PROFILE_TEXT


def test_the_prompt_has_bands_not_raw_scores():
    llm = FakeLLM(["Reapply every two hours [kb-sun-sunscreen-use]."])
    run(IN_KB, llm)
    blob = " ".join(m["content"] for m in llm.calls[0])
    assert "acne High" in blob
    assert not any(f"({v})" in blob for v in (87, 74, 93, 66, 81))
    assert "sentinel-source-text" not in blob and "sentinel-merge-version" not in blob


SENTINEL_MESSAGE = "zqxj-sentinel-message how often should I reapply sunscreen"
SENTINEL_HISTORY = "zqxj-sentinel-history"
SENTINEL_ANSWER = "zqxj-sentinel-answer"


@pytest.mark.parametrize("case", ["template", "unavailable", "line", "coverage", "context", "answered", "gate",
                                  "no_answer", "stream_error"])
def test_no_log_record_holds_any_text(case, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG)
    message = SENTINEL_MESSAGE
    llm = FakeLLM([f"{SENTINEL_ANSWER} reapply [kb-sun-sunscreen-use]. "])
    if case == "template":
        message = f"{SENTINEL_MESSAGE} my lips are swelling"
    elif case == "unavailable":
        llm = FakeLLM(available=False)
    elif case == "line":
        message = "zqxj-sentinel-message recipe"
    elif case == "coverage":
        monkeypatch.setattr(cfg, "TERM_COVERAGE_MIN", 0.99)
    elif case == "context":
        monkeypatch.setattr(cfg, "MODEL_OPTIONS", {**cfg.MODEL_OPTIONS, "num_ctx": 400, "num_predict": 50})
    elif case == "gate":
        llm = FakeLLM([f"{SENTINEL_ANSWER}. It cures acne."])
    elif case == "no_answer":
        llm = FakeLLM(["[NO_ANSWER]"])
    elif case == "stream_error":
        llm = FakeLLM([f"{SENTINEL_ANSWER}. ", "more"], fail_after=1)
    try:
        run(message, llm, [Turn("user", SENTINEL_HISTORY), Turn("assistant", SENTINEL_HISTORY)])
    except LLMUnavailable:
        pass
    records = [r.getMessage() for r in caplog.records]
    assert records, "the turn logs one metadata line"
    for line in records:
        for secret in ("zqxj", "sentinel", "kb-", "swelling", "E1", "emergency_allergy", "reapply"):
            assert secret not in line, (case, line)
