"""The output gate (7d, Units 2-3): every sentence of the model's answer is checked as it
arrives, and the answer is released only when the model's stream has ended (STOP 6, F1: a
[NO_ANSWER] anywhere turns the whole answer into the fixed "I don't know", so nothing can
go out before the end). A stop still closes the model's stream at once. Pure: no I/O, no
logging.

Per sentence, in order:
- thinking text (<think>...</think>) is removed and never sent;
- [NO_ANSWER] (any case; "[no answer]", "[no_answer]") anywhere: the whole answer becomes
  the fixed "I don't know", whatever came before it (F1);
- citations [kb-...] must be notes that were sent with the question ([profile] is allowed);
  others are dropped and counted;
- product markers [P12] must be in the user's routine (picks and alternatives); the server
  swaps in the product's name. An unknown marker stops the answer;
- any other bracket, "[" or "]" (a reasoning note such as "[NOTE: ...]", "[Safety Rule 1]",
  a link), stops the answer (F4);
- a phone number (chat_config.PHONE_PATTERNS: an emergency or helpline number, 5+ digits,
  or three digit groups) in the model's own words stops the answer: numbers reach the user
  only from the sourced templates (Unit 3, STOP 5);
- a run of chat_config.PROMPT_OVERLAP_WORDS words that also appears in the system rules
  (across sentence boundaries) stops the answer (F5). A paraphrase of the rules passes;
- a product name repeated around its marker ("[P7] Brand Gel" becomes "Brand Gel Brand
  Gel" after the swap) is collapsed to one (F3; exact repeats only, any case);
- the claim list (claims.py): a match stops the answer. It also matches negations ("is not
  guaranteed", "not a diagnosis"): fail-closed, by design (F2);
- the answer is cut at chat_config.MAX_ANSWER_CHARS.
On a stop the sentences checked before it are released, and the pipeline adds the fixed
closing line.
"""

import re
from collections import Counter
from dataclasses import dataclass

from . import chat_config as cfg
from .claims import claims_in

_CITE = re.compile(cfg.CITATION_PATTERN)
_PRODUCT = re.compile(cfg.PRODUCT_MARKER_PATTERN)
_NO_ANSWER = re.compile(cfg.NO_ANSWER_PATTERN, re.IGNORECASE)
_PHONES = tuple(re.compile(p) for p in cfg.PHONE_PATTERNS)
_BOUNDARY = re.compile(r"[.!?](?=\s)|\n")
_WORD = re.compile(r"[a-z0-9]+")


def words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


_RULE_WORDS = words(cfg.SYSTEM_PROMPT)
_N = cfg.PROMPT_OVERLAP_WORDS
_RULE_RUNS = frozenset(tuple(_RULE_WORDS[i:i + _N]) for i in range(len(_RULE_WORDS) - _N + 1))


@dataclass(frozen=True)
class Released:
    text: str  # markers removed, product names swapped in ("" when the piece only cited)
    cites: tuple[str, ...]


class Gate:
    def __init__(self, sent_chunk_ids, products: dict[int, str]):
        self.allowed_cites = set(sent_chunk_ids) | {"profile"}
        self.products = products
        self.buffer = ""
        self.stop_reason: str | None = None
        self.held: list[Released] = []  # checked, waiting for the end of the stream
        self.held_chars = 0
        self.tail: list[str] = []  # the last words checked, for runs across sentences
        self.released_sentences = 0  # set by finish()
        self.counts = Counter()  # blocked/dropped events by kind (for the block rate)
        self._collapse = [re.compile(rf"({re.escape(name)})(?:\s*[(:,\-–—]\s*|\s+){re.escape(name)}\)?",
                                     re.IGNORECASE) for name in set(products.values()) if name]

    @property
    def stopped(self) -> bool:
        return self.stop_reason is not None

    def _stop(self, reason: str) -> None:
        self.stop_reason = reason
        self.counts[reason] += 1

    def _strip_thinking(self) -> None:
        while cfg.THINK_OPEN in self.buffer:
            start = self.buffer.index(cfg.THINK_OPEN)
            end = self.buffer.find(cfg.THINK_CLOSE, start)
            if end < 0:
                return  # wait for the close tag; nothing after <think> is checked meanwhile
            self.buffer = self.buffer[:start] + self.buffer[end + len(cfg.THINK_CLOSE):]
            self.counts["thinking"] += 1

    def _checkable(self) -> str:
        """The part of the buffer that can be split into sentences (before any open <think>)."""
        cut = self.buffer.find(cfg.THINK_OPEN)
        return self.buffer if cut < 0 else self.buffer[:cut]

    def _overlaps_rules(self, text: str) -> bool:
        run = self.tail + words(text)
        hit = any(tuple(run[i:i + _N]) in _RULE_RUNS for i in range(len(run) - _N + 1))
        self.tail = run[-(_N - 1):]
        return hit

    def _check(self, sentence: str) -> None:
        if _NO_ANSWER.search(sentence):
            return self._stop("no_answer")
        cites = []
        for cite in _CITE.findall(sentence):
            if cite in self.allowed_cites:
                cites.append(cite)
            else:
                self.counts["invalid_citation"] += 1
        text = _CITE.sub("", sentence)
        for marker in _PRODUCT.findall(text):
            if int(marker) not in self.products:
                return self._stop("unknown_product")
        own_words = _PRODUCT.sub("", text)  # not the product names the server swaps in
        if "[" in own_words or "]" in own_words:
            return self._stop("bracket")
        if any(p.search(own_words) for p in _PHONES):
            return self._stop("number")
        if self._overlaps_rules(own_words):
            return self._stop("prompt")
        text = _PRODUCT.sub(lambda m: self.products[int(m.group(1))], text)
        text = re.sub(r"\s+([.,;:!?])", r"\1", re.sub(r"[ \t]+", " ", text)).strip()
        for pattern in self._collapse:
            text, n = pattern.subn(r"\1", text)
            self.counts["doubled_name"] += n
        if claims_in(text):
            return self._stop("claim")
        if self.held_chars + len(text) > cfg.MAX_ANSWER_CHARS:
            return self._stop("length")
        if not text and not cites:
            return None
        self.held_chars += len(text)
        self.held.append(Released(text, tuple(dict.fromkeys(cites))))
        return None

    def feed(self, piece: str) -> None:
        """Check every complete sentence in the stream so far. Nothing is released here."""
        if self.stopped:
            return
        self.buffer += piece
        self._strip_thinking()
        while not self.stopped:
            head = self._checkable()
            m = _BOUNDARY.search(head)
            if not m:
                break
            sentence, self.buffer = head[:m.end()], self.buffer[m.end():]
            if sentence.strip():
                self._check(sentence.strip())

    def finish(self, truncated: bool = False) -> list[Released]:
        """The answer, at the end of the stream: every sentence checked before any stop, or
        nothing at all after a [NO_ANSWER]. An unclosed <think> is dropped. `truncated`: the
        model hit its token limit (num_predict), so an unfinished last sentence is dropped and
        counted rather than sent cut off."""
        if not self.stopped:
            rest = self._checkable().strip()
            if cfg.THINK_OPEN in self.buffer:
                self.counts["thinking"] += 1
            self.buffer = ""
            if rest and truncated and rest[-1] not in ".!?":
                self.counts["truncated"] += 1
            elif rest:
                self._check(rest)
        out = [] if self.stop_reason == "no_answer" else self.held
        self.released_sentences = sum(1 for r in out if r.text)
        return out
