"""The question files: hashes recorded once and checked, the split, and the parsers.

user_questions.txt is read only through eval_files; no test prints its text."""

import json
import shutil
from collections import Counter

import pytest

from app.services.chat import eval_files as ef
from app.services.chat.kb import load_kb


def test_the_recorded_hashes_still_match():
    data = ef.check_hashes()
    assert set(data["question_files"]) == {"author_questions.json", "user_questions.txt"}


def test_a_changed_question_file_is_caught(tmp_path):
    for name in ("author_questions.json", "user_questions.txt", "metadata.json"):
        shutil.copy(ef.EVAL_DIR / name, tmp_path / name)
    ef.check_hashes(tmp_path / "metadata.json", tmp_path)
    (tmp_path / "user_questions.txt").write_text("1. A different question?\n", encoding="utf-8")
    with pytest.raises(ef.EvalFileError, match="user_questions.txt"):
        ef.check_hashes(tmp_path / "metadata.json", tmp_path)


def test_hashes_are_recorded_once(tmp_path):
    files = (tmp_path / "q.json",)
    files[0].write_text("{}", encoding="utf-8")
    ef.record_hashes(tmp_path / "metadata.json", files)
    with pytest.raises(ef.EvalFileError, match="once"):
        ef.record_hashes(tmp_path / "metadata.json", files)


QUESTIONS = ef.load_author_questions()


def test_the_split_is_as_planned():
    """42 in all: dev 14 (the author's), test 8 (the author's) + 20 external."""
    assert Counter(q.split for q in QUESTIONS) == {"dev": 14, "test": 8}
    assert Counter(q.group for q in QUESTIONS if q.split == "dev") == {
        "in_kb": 5, "profile": 2, "unanswerable": 2, "out_of_scope": 2, "injection": 2, "red_flag": 1}
    assert Counter(q.group for q in QUESTIONS if q.split == "test") == {
        "in_kb": 2, "profile": 2, "out_of_scope": 1, "injection": 2, "red_flag": 1}
    assert len(ef.load_user_questions()) == 20


def test_labels_name_real_chunks_and_fit_their_group():
    ids = set(load_kb().ids)
    for q in QUESTIONS:
        assert set(q.relevant + q.acceptable) <= ids, q.id
        if q.group in ("in_kb", "profile"):
            assert q.relevant and q.expect == "answer", q.id
        else:
            assert not q.relevant, q.id


def test_false_positive_probes_are_in_both_splits():
    assert Counter(q.split for q in QUESTIONS if q.fp_probe) == {"dev": 3, "test": 2}


def test_user_questions_parse_strictly(tmp_path):
    path = tmp_path / "q.txt"
    path.write_text("1. First?\n\n2. Second?\n", encoding="utf-8")
    assert [q.number for q in ef.load_user_questions(path)] == [1, 2]
    path.write_text("1. First?\nnot numbered\n", encoding="utf-8")
    with pytest.raises(ef.EvalFileError):
        ef.load_user_questions(path)
    path.write_text("1. First?\n3. Third?\n", encoding="utf-8")
    with pytest.raises(ef.EvalFileError):
        ef.load_user_questions(path)


def test_user_labels(tmp_path):
    path = tmp_path / "labels.json"
    assert ef.load_user_labels([1, 2], path) is None
    path.write_text(json.dumps({"1": ["kb-sun-uv"], "2": "not_covered"}), encoding="utf-8")
    assert ef.load_user_labels([1, 2], path) == {1: ("kb-sun-uv",), 2: "not_covered"}
    path.write_text(json.dumps({"1": ["kb-sun-uv"]}), encoding="utf-8")
    with pytest.raises(ef.EvalFileError, match="question 2"):
        ef.load_user_labels([1, 2], path)
    path.write_text(json.dumps({"1": [], "2": "not_covered", "9": "not_covered"}), encoding="utf-8")
    with pytest.raises(ef.EvalFileError):
        ef.load_user_labels([1, 2], path)
