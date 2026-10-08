"""The evaluation's rules: the threshold rule, Wilson intervals, the freeze and its scope,
the one test run, and the external section staying withheld until the user's mapping exists."""

import json
import re

import pytest

from app.services.chat import chat_config as cfg
from app.services.chat import eval_files as ef
from app.services.chat import evaluate as ev
from app.services.chat.kb import load_kb
from app.services.chat.retrieval import build_index
from app.tests import test_config_versions


def test_the_fingerprint_matches_the_config_guard():
    assert ev.config_fingerprint(cfg, "CHAT_CONFIG_VERSION") == test_config_versions.fingerprint(
        cfg, "CHAT_CONFIG_VERSION")


def test_wilson():
    lo, hi = ev.wilson(27, 30)
    assert lo == pytest.approx(0.744, abs=0.002) and hi == pytest.approx(0.965, abs=0.002)
    assert ev.wilson(0, 0) == (0.0, 1.0)
    assert ev.wilson(5, 5)[1] == 1.0


def test_choose_line():
    assert ev.choose_line([5, 6], [1, 2]) == 3.5  # one clean gap: its middle
    assert ev.choose_line([4, 5], [1]) == 2.5
    assert ev.choose_line([3, 9], [1, 6]) == 2.0  # tied at 2 and 7.5: the lower middle
    assert ev.choose_line([], [1]) == 2.0  # nothing to keep: one above the top score refuses all


# --- the freeze and its scope -------------------------------------------------------------

def test_the_freeze_covers_every_setting_retrieval_reads():
    used = set(re.findall(r"\bcfg\.([A-Z][A-Z0-9_]*)", ev.RETRIEVAL_CODE.read_text(encoding="utf-8")))
    assert used <= set(ev.FROZEN_RETRIEVAL_KEYS), f"not frozen: {sorted(used - set(ev.FROZEN_RETRIEVAL_KEYS))}"


def test_the_freeze(tmp_path, monkeypatch):
    kb, metadata = load_kb(), ef.check_hashes()
    path = tmp_path / "freeze.json"
    with pytest.raises(ev.EvaluationError, match="missing"):
        ev.check_freeze(kb, metadata, path)
    ev.freeze(kb, metadata, path)
    ev.check_freeze(kb, metadata, path)
    with pytest.raises(ev.EvaluationError, match="once"):
        ev.freeze(kb, metadata, path)
    monkeypatch.setattr(cfg, "TOP_K", cfg.TOP_K + 1)
    with pytest.raises(ev.EvaluationError, match="retrieval"):
        ev.check_freeze(kb, metadata, path)


def test_router_templates_and_gate_patterns_dont_touch_the_freeze(tmp_path, monkeypatch):
    kb, metadata = load_kb(), ef.check_hashes()
    path = tmp_path / "freeze.json"
    ev.freeze(kb, metadata, path)
    monkeypatch.setattr(cfg, "CLAIM_PATTERNS", (*cfg.CLAIM_PATTERNS, ("new", r"\bnew\b")))
    monkeypatch.setattr(cfg, "ROUTER_TERMS", ("mole",), raising=False)
    monkeypatch.setattr(cfg, "CHAT_CONFIG_VERSION", "chat-9.9.9")
    ev.check_freeze(kb, metadata, path)


def test_no_freeze_without_a_line(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "NO_ANSWER_MIN_SCORE", None)
    with pytest.raises(ev.EvaluationError, match="isn't set"):
        ev.freeze(load_kb(), ef.check_hashes(), tmp_path / "freeze.json")


def test_a_changed_retrieval_code_breaks_the_freeze(tmp_path):
    kb, metadata = load_kb(), ef.check_hashes()
    path = tmp_path / "freeze.json"
    ev.freeze(kb, metadata, path)
    record = json.loads(path.read_text(encoding="utf-8"))
    record["retrieval_code_sha256"] = "0" * 64
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ev.EvaluationError, match="retrieval_code_sha256"):
        ev.check_freeze(kb, metadata, path)


def old_freeze(kb, metadata, path, **override):
    record = {"frozen_at": "2026-10-08T08:46:15+00:00", "note": "Set on the dev questions only.",
              **ev._whole_config_record(kb, metadata), **override}
    path.write_text(json.dumps(record), encoding="utf-8")


def test_rescoping_keeps_the_frozen_settings(tmp_path):
    kb, metadata = load_kb(), ef.check_hashes()
    path = tmp_path / "freeze.json"
    old_freeze(kb, metadata, path)
    record = ev.rescope_freeze(kb, metadata, path)
    assert record["frozen_at"] == "2026-10-08T08:46:15+00:00"
    assert record["previous_scope"]["chat_config"]["fingerprint"] == ev.config_fingerprint(cfg, "CHAT_CONFIG_VERSION")
    ev.check_freeze(kb, metadata, path)
    with pytest.raises(ev.EvaluationError, match="already"):
        ev.rescope_freeze(kb, metadata, path)


def test_rescoping_refuses_a_freeze_that_no_longer_verifies(tmp_path):
    kb, metadata = load_kb(), ef.check_hashes()
    path = tmp_path / "freeze.json"
    old_freeze(kb, metadata, path, chat_config={"version": "chat-1.0.0", "fingerprint": "0" * 16})
    with pytest.raises(ev.EvaluationError, match="doesn't verify"):
        ev.rescope_freeze(kb, metadata, path)


# --- the one test run, and the external section --------------------------------------------

def test_external_results_are_withheld_until_the_mapping_exists(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ef, "USER_LABELS", tmp_path / "user_question_labels.json")
    kb = load_kb()
    assert ev.external_section(build_index(kb), kb, cfg.NO_ANSWER_MIN_SCORE) is None
    out = capsys.readouterr().out
    assert "withheld" in out
    assert not any(q.question in out for q in ef.load_user_questions())


def test_the_test_split_runs_once_and_only_with_the_mapping(tmp_path, monkeypatch, capsys):
    """On stand-in external questions, so no result on the real ones is ever computed here."""
    kb, metadata = load_kb(), ef.check_hashes()
    freeze_path, results_path = tmp_path / "freeze.json", tmp_path / "test_results.json"
    ev.freeze(kb, metadata, freeze_path)
    questions = tmp_path / "user_questions.txt"
    questions.write_text("1. How often should I reapply sunscreen?\n2. What is the capital of France?\n",
                         encoding="utf-8")
    monkeypatch.setattr(ef, "USER_QUESTIONS", questions)
    monkeypatch.setattr(ef, "USER_LABELS", tmp_path / "user_question_labels.json")
    with pytest.raises(ev.EvaluationError, match="mapping"):
        ev.run_test(kb, metadata, freeze_path, results_path)
    ef.USER_LABELS.write_text(json.dumps({"1": ["kb-sun-sunscreen-use"], "2": "not_covered"}), encoding="utf-8")
    record = ev.run_test(kb, metadata, freeze_path, results_path)
    capsys.readouterr()
    assert record["external"]["covered"] == 1 and record["external"]["not_covered"] == 1
    assert record["external"]["not_covered_refused_at_line"]["k"] == 1
    assert record["user_question_labels_sha256"] == ef.sha256_of(ef.USER_LABELS)
    assert json.loads(results_path.read_text(encoding="utf-8"))["freeze"]["retrieval"]
    with pytest.raises(ev.EvaluationError, match="once"):
        ev.run_test(kb, metadata, freeze_path, results_path)
