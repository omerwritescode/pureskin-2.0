"""Term coverage (7d, Unit 2): a check after retrieval and before the model, outside the
retrieval freeze (it reads retrieval's tokeniser but changes nothing in retrieval.py).

The share of the question's content words (retrieval's tokens: stopwords out, plurals
stemmed, spellings mapped, question idioms removed) that appear in the best chunk's title,
aliases or text. Below chat_config.TERM_COVERAGE_MIN, the question gets the fixed "I don't
know" without a model call: BM25 alone lets in-domain questions through on common words
(README, "The no-answer line is a lexical filter").
"""

from . import chat_config as cfg
from .retrieval import chunk_tokens, question_tokens


def coverage(question: str, chunk) -> float:
    terms = set(question_tokens(question))
    if not terms:
        return 0.0
    return len(terms & set(chunk_tokens(chunk))) / len(terms)


def covered(question: str, chunk, minimum: float | None = None) -> bool:
    """True while no minimum is set (None)."""
    minimum = cfg.TERM_COVERAGE_MIN if minimum is None else minimum
    return minimum is None or coverage(question, chunk) >= minimum
