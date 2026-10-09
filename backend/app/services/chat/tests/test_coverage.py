"""Term coverage: what it measures, and that it sits outside the retrieval freeze."""

from types import SimpleNamespace

from app.services.chat import chat_config as cfg
from app.services.chat import eval_files as ef
from app.services.chat import evaluate as ev
from app.services.chat.coverage import coverage, covered
from app.services.chat.kb import load_kb

CHUNK = SimpleNamespace(title="Using sunscreen", aliases=("spf",), text="Reapply sunscreen every two hours.")


def test_coverage_is_the_share_of_content_words_in_the_chunk():
    assert coverage("How often should I reapply sunscreen?", CHUNK) == 2 / 3  # often, reapply, sunscreen
    assert coverage("SPF", CHUNK) == 1.0
    assert coverage("what is the", CHUNK) == 0.0  # no content words


def test_covered_uses_the_minimum():
    assert covered("collagen supplements", CHUNK, 0.5) is False
    assert covered("reapply sunscreen", CHUNK, 0.5) is True


def test_the_check_is_outside_the_retrieval_freeze(monkeypatch):
    assert "TERM_COVERAGE_MIN" not in ev.FROZEN_RETRIEVAL_KEYS
    assert ev.RETRIEVAL_CODE.name == "retrieval.py"  # coverage.py is not the frozen code
    monkeypatch.setattr(cfg, "TERM_COVERAGE_MIN", 0.99)
    ev.check_freeze(load_kb(), ef.check_hashes())  # the committed freeze still verifies
