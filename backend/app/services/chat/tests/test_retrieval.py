"""BM25 by hand: tokeniser, scores checked against the formula worked out by hand,
determinism and the no-answer line."""

import math

import pytest

from app.services.chat.kb import load_kb
from app.services.chat.retrieval import BM25Index, build_index, question_tokens, retrieve, stem, tokens


@pytest.mark.parametrize(("word", "expected"), [
    ("blackheads", "blackhead"), ("patches", "patch"), ("boxes", "box"), ("classes", "class"),
    ("glasses", "glass"), ("flies", "fly"), ("status", "status"), ("acne", "acne"),
    ("gas", "gas"),  # the stem would be shorter than MIN_STEM
])
def test_plurals(word, expected):
    assert stem(word) == expected


def test_tokens():
    assert tokens("What are BLACKHEADS?") == ["blackhead"]
    assert tokens("My skin's colour") == ["skin", "color"]
    assert tokens("moisturisers for ageing skin") == ["moisturizer", "aging", "skin"]
    assert tokens("Don't use it, please help") == []


def test_the_question_idiom_goes_but_normal_skin_stays():
    assert "normal" not in question_tokens("My retinol stings. Is that normal?")
    assert "normal" not in question_tokens("Is it normal for skin to peel?")
    assert "normal" in question_tokens("Is my skin normal or dry?")
    assert "normal" in tokens("Is that normal?")  # chunks are never touched


# A three-document corpus small enough to score by hand. N = 3, average length 3.
DOCS = {"a": ["sun", "sun", "cream"], "b": ["acne", "cream"], "c": ["mole", "check", "mole", "sun"]}
K1, B = 1.2, 0.75


def test_scores_match_the_formula_worked_by_hand():
    index = BM25Index(DOCS, K1, B)
    idf_sun = math.log(1 + (3 - 2 + 0.5) / (2 + 0.5))  # df 2
    idf_cream = idf_sun  # df 2
    idf_acne = math.log(1 + (3 - 1 + 0.5) / (1 + 0.5))  # df 1
    # a: tf 2, length 3 -> K1 * (1 - B + B * 3/3) = 1.2
    # c: tf 1, length 4 -> K1 * (1 - B + B * 4/3) = 1.5
    assert index.scores(["sun"]) == pytest.approx({"a": idf_sun * 2 * 2.2 / (2 + 1.2),
                                                   "c": idf_sun * 1 * 2.2 / (1 + 1.5)}, abs=1e-12)
    # b: length 2 -> K1 * (1 - B + B * 2/3) = 0.9
    assert index.scores(["acne", "cream"])["b"] == pytest.approx(
        idf_acne * 2.2 / (1 + 0.9) + idf_cream * 2.2 / (1 + 0.9), abs=1e-12)


def test_a_repeated_question_word_counts_once():
    index = BM25Index(DOCS, K1, B)
    assert index.scores(["sun", "sun"]) == index.scores(["sun"])


def test_ties_break_by_chunk_id_and_results_repeat_exactly():
    index = BM25Index({"y": ["sun"], "x": ["sun"], "z": ["mole"]}, K1, B)
    first = index.search("sun", k=4)
    assert [h.chunk_id for h in first] == ["x", "y"]
    assert all(index.search("sun", k=4) == first for _ in range(5))


def test_top_k_and_the_no_answer_line():
    index = BM25Index(DOCS, K1, B)
    assert len(index.search("sun cream acne mole", k=2)) == 2
    hits = retrieve(index, "acne", k=4, min_score=None)
    assert hits.answerable and hits.ids == ("b",)
    assert not retrieve(index, "acne", k=4, min_score=hits.top_score + 0.01).answerable
    assert retrieve(index, "acne", k=4, min_score=hits.top_score).answerable
    nothing = retrieve(index, "weather tomorrow", k=4, min_score=None)
    assert not nothing.answerable and nothing.hits == () and nothing.top_score == 0.0


def test_the_real_kb_returns_known_chunks():
    kb = load_kb()
    result = retrieve(build_index(kb), "how often should I reapply sunscreen")
    assert result.ids and set(result.ids) <= set(kb.ids)
    assert result.ids[0] == "kb-sun-sunscreen-use"
