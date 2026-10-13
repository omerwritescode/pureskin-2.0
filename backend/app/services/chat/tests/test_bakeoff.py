"""The bake-off harness's own parsing and checks (no Ollama): `ollama ps` rows, the injection
checks, the intervals and the question sets."""

import collections

import pytest

from app.services.chat import bakeoff
from app.services.chat import chat_config as cfg

PS = """NAME                    ID              SIZE      PROCESSOR          CONTEXT    UNTIL
qwen3.5:4b-q4_K_M       d8b0f5e9760c    4.1 GB    100% GPU           4096       4 minutes from now
qwen3.5:9b-q4_K_M       56671c2ab938    6.4 GB    12%/88% CPU/GPU    8192       2 hours from now
"""


def test_ollama_ps_rows():
    assert bakeoff.parse_ps("NAME    ID    SIZE    PROCESSOR    CONTEXT    UNTIL\n") == []
    assert bakeoff.parse_ps("") == []
    rows = bakeoff.parse_ps(PS)
    assert [(r["name"], r["processor"], r["context"]) for r in rows] == [
        ("qwen3.5:4b-q4_K_M", "100% GPU", "4096"), ("qwen3.5:9b-q4_K_M", "12%/88% CPU/GPU", "8192")]


def test_the_question_sets():
    counts = collections.Counter((q["set"], q["expect"]) for q in bakeoff.questions())
    assert counts == {("dev", "answer"): 7, ("dev", "no_answer"): 5, ("dev", "template:prescription"): 1,
                      ("dev", "template:mole"): 1, ("dev_uncovered", "no_answer"): 15,
                      ("dev_injection", "no_break"): 6, ("external", "answer"): 9, ("external", "no_answer"): 11}


def test_injection_checks():
    profile, brands = bakeoff.bakeoff_profile()
    own = next(iter(profile.products))
    rules = " ".join(cfg.SYSTEM_PROMPT.split()[5:16])
    sent = ("kb-sun-uv",)
    assert bakeoff.broken("prompt_leak", f"Sure. {rules}", sent, profile, brands)
    assert not bakeoff.broken("prompt_leak", "Reapply sunscreen every two hours.", sent, profile, brands)
    assert bakeoff.broken("invented_product", "Try [P999].", sent, profile, brands)
    assert not bakeoff.broken("invented_product", f"Your routine has [P{own}].", sent, profile, brands)
    other = next(b for b in brands if b.lower() not in " ".join(profile.products.values()).lower())
    assert bakeoff.broken("invented_product", f"Buy something from {other}.", sent, profile, brands)
    assert bakeoff.broken("claim", "Sunscreen is guaranteed to prevent wrinkles.", sent, profile, brands)
    assert bakeoff.broken("invalid_citation", "Reapply [kb-dermatologist-approved].", sent, profile, brands)
    assert not bakeoff.broken("invalid_citation", "Reapply [kb-sun-uv] [profile].", sent, profile, brands)
    assert bakeoff.broken("persona", "As a dermatologist, I suggest...", sent, profile, brands)
    assert not bakeoff.broken("persona", "A dermatologist can help with that.", sent, profile, brands)


def test_the_new_questions_load_only_with_their_recorded_hashes(tmp_path, monkeypatch):
    assert len(bakeoff.new_questions()) == 37
    changed = tmp_path / "new_covered.json"
    changed.write_bytes(bakeoff.NEW_QUESTIONS["new_covered.json"].read_bytes() + b" ")
    monkeypatch.setitem(bakeoff.NEW_QUESTIONS, "new_covered.json", changed)
    with pytest.raises(SystemExit, match="changed since its hash was recorded"):
        bakeoff.new_questions()


def test_the_after_fixes_summary():
    def rec(set_, outcome, routine=False, route="model", raw="", arrive=1.0):
        return {"set": set_, "outcome": outcome, "about_routine": routine, "route": route, "raw": raw,
                "first_sentence_s": arrive if route == "model" else 0.01, "tokens_per_s": 70.0}

    result = {"model": "m", "chat_config": "chat-x", "records": [
        rec("new_uncovered", "no_answer_ingredient", route="no_answer"),
        rec("new_uncovered", "no_answer_model"), rec("new_uncovered", "answered"),
        rec("new_covered", "answered", routine=True), rec("new_covered", "no_answer_ingredient", routine=True,
                                                          route="no_answer"),
        rec("new_covered", "gate_bracket", raw="Fact [kb-a, kb-b]. More", arrive=3.0),
        rec("new_covered", "gate_bracket", raw="Fact [NOTE: x]", arrive=2.0)]}
    s = bakeoff.summarise_new(result)
    assert s["fixed_no_answer_new_uncovered"].startswith("2/3")
    assert s["check_blocked_new_uncovered"].startswith("1/3")
    assert s["check_false_blocks_new_covered"].startswith("1/4") and s["check_false_blocks_routine"].startswith("1/2")
    assert s["gate_stop_reasons"] == {"gate_bracket": 2} and s["bracket_stops_multi_id"] == "1/2"
    assert s["answer_arrives_s_median"] == 1.0 and s["answer_arrives_n"] == 5  # model-route turns only


def test_wilson():
    assert bakeoff.wilson(5, 10) == "5/10 (0.24-0.76)"
    assert bakeoff.wilson(0, 0) == "n/a"


def test_ollama_ps_rows_with_the_runner_column():
    text = ("NAME                 ID              SIZE      PROCESSOR    CONTEXT    RUNNER      UNTIL\n"
            "qwen3.5:4b-q4_K_M    d8b0f5e9760c    3.1 GB    100% GPU     4096       llamacpp    4 minutes from now\n")
    (row,) = bakeoff.parse_ps(text)
    assert (row["processor"], row["context"], row["runner"]) == ("100% GPU", "4096", "llamacpp")
