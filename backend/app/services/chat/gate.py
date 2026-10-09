"""The output gate (7d, Unit 2): the model's answer is released one sentence at a time, and
only after the sentence passes every check. Pure: no I/O, no logging.

Per sentence, in order:
- thinking text (<think>...</think>) is removed and never sent;
- [NO_ANSWER] stops the answer: the fixed "I don't know" if nothing was sent yet;
- citations [kb-...] must be notes that were sent with the question ([profile] is allowed);
  others are dropped and counted;
- product markers [P12] must be in the user's routine (picks and alternatives); the server
  swaps in the product's name. An unknown marker stops the answer (the sentence is held back);
- the claim list (claims.py): a match stops the answer (the sentence is held back);
- the answer is cut at chat_config.MAX_ANSWER_CHARS.
A stop ends the model's stream; the pipeline then sends the fixed closing line.
"""

import re
from collections import Counter
from dataclasses import dataclass

from . import chat_config as cfg
from .claims import claims_in

_CITE = re.compile(cfg.CITATION_PATTERN)
_PRODUCT = re.compile(cfg.PRODUCT_MARKER_PATTERN)
_BOUNDARY = re.compile(r"[.!?](?=\s)|\n")


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
        self.released_chars = 0
        self.released_sentences = 0
        self.counts = Counter()  # blocked/dropped events by kind (for the block rate)

    @property
    def stopped(self) -> bool:
        return self.stop_reason is not None

    def _stop(self, reason: str) -> list[Released]:
        self.stop_reason = reason
        self.counts[reason] += 1
        return []

    def _strip_thinking(self) -> None:
        while cfg.THINK_OPEN in self.buffer:
            start = self.buffer.index(cfg.THINK_OPEN)
            end = self.buffer.find(cfg.THINK_CLOSE, start)
            if end < 0:
                return  # wait for the close tag; nothing after <think> is released meanwhile
            self.buffer = self.buffer[:start] + self.buffer[end + len(cfg.THINK_CLOSE):]
            self.counts["thinking"] += 1

    def _releasable(self) -> str:
        """The part of the buffer that can be split into sentences (before any open <think>)."""
        cut = self.buffer.find(cfg.THINK_OPEN)
        return self.buffer if cut < 0 else self.buffer[:cut]

    def _check(self, sentence: str) -> list[Released]:
        if cfg.NO_ANSWER_MARKER in sentence:
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
        text = _PRODUCT.sub(lambda m: self.products[int(m.group(1))], text)
        text = re.sub(r"\s+([.,;:!?])", r"\1", re.sub(r"[ \t]+", " ", text)).strip()
        if claims_in(text):
            return self._stop("claim")
        if self.released_chars + len(text) > cfg.MAX_ANSWER_CHARS:
            return self._stop("length")
        if not text and not cites:
            return []
        self.released_chars += len(text)
        self.released_sentences += bool(text)
        return [Released(text, tuple(dict.fromkeys(cites)))]

    def feed(self, piece: str) -> list[Released]:
        if self.stopped:
            return []
        self.buffer += piece
        self._strip_thinking()
        out = []
        while not self.stopped:
            head = self._releasable()
            stripped = head.lstrip()
            if stripped and cfg.NO_ANSWER_MARKER.startswith(stripped[:len(cfg.NO_ANSWER_MARKER)]) \
                    and len(stripped) < len(cfg.NO_ANSWER_MARKER):
                break  # could still become [NO_ANSWER]: wait
            m = _BOUNDARY.search(head)
            if not m:
                break
            sentence, self.buffer = head[:m.end()], self.buffer[m.end():]
            if sentence.strip():
                out += self._check(sentence.strip())
        return out

    def finish(self) -> list[Released]:
        """The rest of the answer, at the end of the stream (an unclosed <think> is dropped)."""
        if self.stopped:
            return []
        rest = self._releasable().strip()
        if cfg.THINK_OPEN in self.buffer:
            self.counts["thinking"] += 1
        self.buffer = ""
        return self._check(rest) if rest else []
