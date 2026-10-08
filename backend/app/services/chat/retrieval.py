"""Hand-written BM25 over the knowledge base (7d). Pure and deterministic: the same
question always gives the same chunks in the same order (ties broken by chunk id).

    score(q, d) = sum over the distinct query terms t found in d of
                  idf(t) * tf * (k1 + 1) / (tf + k1 * (1 - b + b * len(d) / avg_len))
    idf(t)      = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))

A chunk's text for retrieval is its title, aliases and text. A question whose best score
is below chat_config.NO_ANSWER_MIN_SCORE gets the fixed "I don't know" reply.

    python -m app.services.chat.retrieval "how often should I reapply sunscreen"
"""

import math
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass

from . import chat_config as cfg

_TOKEN = re.compile(cfg.TOKEN_PATTERN)
_STOPWORDS = frozenset(cfg.STOPWORDS)
_IDIOMS = tuple(re.compile(p, re.IGNORECASE) for p in cfg.QUESTION_IDIOMS)


def stem(word: str) -> str:
    """Plural endings only (chat_config.PLURAL_RULES): "blackheads" -> "blackhead"."""
    if word.endswith(cfg.KEEP_ENDINGS):
        return word
    for ending, replacement in cfg.PLURAL_RULES:
        if word.endswith(ending):
            stemmed = word[: -len(ending)] + replacement
            return stemmed if len(stemmed) >= cfg.MIN_STEM else word
    return word


def tokens(text: str) -> list[str]:
    """Lowercase, apostrophes dropped, stopwords out (before and after stemming), plurals
    stemmed, British spellings mapped to one form."""
    text = unicodedata.normalize("NFKC", text).lower()
    text = text.replace("'", "").replace("’", "").replace("‘", "")
    out = []
    for raw in _TOKEN.findall(text):
        if raw in _STOPWORDS:
            continue
        word = stem(raw)
        word = cfg.SPELLING.get(word, word)
        if word not in _STOPWORDS:
            out.append(word)
    return out


def question_tokens(question: str) -> list[str]:
    """tokens() after removing the question idioms (chat_config.QUESTION_IDIOMS)."""
    for idiom in _IDIOMS:
        question = idiom.sub(" ", question.replace("’", "'"))
    return tokens(question)


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    score: float


@dataclass(frozen=True)
class Retrieval:
    hits: tuple[Hit, ...]  # best first, at most k
    answerable: bool  # the best score reaches the no-answer line

    @property
    def top_score(self) -> float:
        return self.hits[0].score if self.hits else 0.0

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(h.chunk_id for h in self.hits)


class BM25Index:
    def __init__(self, docs: dict[str, list[str]], k1: float = cfg.BM25_K1, b: float = cfg.BM25_B):
        self.k1, self.b = k1, b
        self.ids = tuple(sorted(docs))
        self.tf = {d: Counter(docs[d]) for d in self.ids}
        self.length = {d: len(docs[d]) for d in self.ids}
        self.avg_length = sum(self.length.values()) / len(self.ids)
        df = Counter(t for d in self.ids for t in self.tf[d])
        n = len(self.ids)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def scores(self, query_tokens: list[str]) -> dict[str, float]:
        """Score of every chunk that shares at least one term with the query."""
        out = {}
        for term in sorted(set(query_tokens)):  # sorted: the same summation order every time
            idf = self.idf.get(term)
            if idf is None:
                continue
            for d in self.ids:
                tf = self.tf[d][term]
                if tf:
                    norm = self.k1 * (1 - self.b + self.b * self.length[d] / self.avg_length)
                    out[d] = out.get(d, 0.0) + idf * tf * (self.k1 + 1) / (tf + norm)
        return out

    def search(self, query: str, k: int = cfg.TOP_K) -> tuple[Hit, ...]:
        ranked = sorted(self.scores(question_tokens(query)).items(), key=lambda item: (-round(item[1], 9), item[0]))
        return tuple(Hit(d, round(s, 4)) for d, s in ranked[:k])


def chunk_tokens(chunk) -> list[str]:
    return tokens(" ".join([chunk.title, *chunk.aliases, chunk.text]))


def build_index(kb) -> BM25Index:
    return BM25Index({c.id: chunk_tokens(c) for c in kb.chunks})


def retrieve(index: BM25Index, question: str, k: int = cfg.TOP_K,
             min_score: float | None = cfg.NO_ANSWER_MIN_SCORE) -> Retrieval:
    """The top k chunks, and whether the best one clears the no-answer line. Until the line
    is set (None), any hit counts as answerable."""
    hits = index.search(question, k)
    top = hits[0].score if hits else 0.0
    answerable = bool(hits) and (min_score is None or top >= min_score)
    return Retrieval(hits, answerable)


def main(argv: list[str] | None = None) -> int:
    from .kb import load_kb

    question = " ".join(argv if argv is not None else sys.argv[1:])
    if not question.strip():
        print('usage: python -m app.services.chat.retrieval "a question"', file=sys.stderr)
        return 2
    kb = load_kb()
    result = retrieve(build_index(kb), question)
    print(f"tokens: {question_tokens(question)}")
    line = cfg.NO_ANSWER_MIN_SCORE
    print(f"no-answer line: {line if line is not None else 'not set yet'}; answerable: {result.answerable}")
    for h in result.hits:
        print(f"  {h.score:8.4f}  {h.chunk_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
