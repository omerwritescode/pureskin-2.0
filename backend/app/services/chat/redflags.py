"""Red-flag router (7d, Unit 2): deterministic and rule-based. Pure: no I/O, no logging.

It runs first, before retrieval and before any model or Ollama check. A matched group
(chat_config.ROUTER_GROUPS, highest priority first) gets a fixed template and never reaches
the model. Otherwise caution lines (chat_config.CAUTIONS) may be appended after the model's
answer.

What is routed (STOP 3 decision 1): the current message, in full, and the user's earlier
turns. Assistant turns are never routed (they carry no user state; a forged one can only
change wording, which the gate checks). A group that fires only because of an earlier user
turn routes to its template for chat_config.HISTORY_TEMPLATE_GROUPS (pregnancy with a
retinoid, self-harm, a child, a severe allergic reaction), and otherwise adds the group's
caution line (chat_config.HISTORY_CAUTION) or nothing.
"""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache

from . import chat_config as cfg


@dataclass(frozen=True)
class Turn:
    role: str  # "user" or "assistant"
    content: str


@dataclass(frozen=True)
class Route:
    kind: str  # "template" (fixed answer, no model), "soft" (model + caution lines) or "none"
    group: str | None = None
    template_id: str | None = None
    cautions: tuple[str, ...] = ()  # caution ids, in chat_config.CAUTION_ORDER
    from_history: bool = False  # the template's group doesn't fire on the current message alone

    @property
    def template_text(self) -> str | None:
        return cfg.TEMPLATES[self.template_id]["text"] if self.template_id else None

    @property
    def caution_texts(self) -> tuple[str, ...]:
        return tuple(cfg.CAUTIONS[c]["text"] for c in self.cautions)


def normalise(text: str) -> str:
    """Lowercase, apostrophes dropped ("won't" -> "wont"), anything else that isn't a letter
    or digit -> one space."""
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"['’‘`]", "", text)
    return " ".join(re.findall(r"[a-z0-9]+", text))


def split_sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


@dataclass(frozen=True)
class _Text:
    normalised: str
    tokens: tuple[str, ...]


def _text(raw: str) -> _Text:
    norm = normalise(raw)
    return _Text(norm, tuple(norm.split()))


@cache
def _phrases(terms: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(normalise(t).split()) for t in terms)


def _positions(tokens: tuple[str, ...], terms: tuple[str, ...]) -> list[int]:
    out = []
    for phrase in _phrases(terms):
        n = len(phrase)
        out += [i for i in range(len(tokens) - n + 1) if tokens[i:i + n] == phrase]
    return out


@cache
def _regexes(patterns: tuple[str, ...]) -> tuple[re.Pattern, ...]:
    conditions = "|".join(re.escape(normalise(c)) for c in cfg.DIAGNOSIS_CONDITIONS)
    return tuple(re.compile(p.replace("{conditions}", conditions)) for p in patterns)


def _clause_fires(clause: tuple, texts: list[_Text]) -> bool:
    kind = clause[0]
    if kind == "any":
        return any(_positions(t.tokens, clause[1]) for t in texts)
    if kind == "all":
        groups, scope = clause[1], clause[2]
        if scope == "conversation":
            return all(any(_positions(t.tokens, g) for t in texts) for g in groups)
        for t in texts:
            found = [_positions(t.tokens, g) for g in groups]
            if not all(found):
                continue
            if scope == "text":
                return True
            if any(all(any(abs(p - q) <= scope for q in others) for others in found[1:]) for p in found[0]):
                return True
        return False
    if kind == "regex":
        return any(r.search(t.normalised) for t in texts for r in _regexes(clause[1]))
    if kind == "age_under":
        for t in texts:
            for pattern in cfg.AGE_PATTERNS:
                if any(int(m.group(1)) < clause[1] for m in re.finditer(pattern, t.normalised)):
                    return True
        return False
    raise ValueError(f"unknown router clause {kind!r}")


def _fires(rule: tuple, texts: list[_Text]) -> bool:
    return any(_clause_fires(clause, texts) for clause in rule)


def route(message: str, history: Sequence[Turn] = ()) -> Route:
    """The route for a message, given the earlier turns (only the user's are read)."""
    current = [_text(message)]
    everything = current + [_text(t.content) for t in history if t.role == "user"]
    cautions = set()
    for group in cfg.ROUTER_PRIORITY:
        rule = cfg.ROUTER_GROUPS[group]
        if _fires(rule, current):
            return Route("template", group, cfg.ROUTER_TEMPLATE[group])
        if len(everything) > 1 and _fires(rule, everything):
            if group in cfg.HISTORY_TEMPLATE_GROUPS:
                return Route("template", group, cfg.ROUTER_TEMPLATE[group], from_history=True)
            if group in cfg.HISTORY_CAUTION:
                cautions.add(cfg.HISTORY_CAUTION[group])
    cautions |= {flag for flag, rule in cfg.SOFT_FLAGS.items() if _fires(rule, everything)}
    ordered = tuple(c for c in cfg.CAUTION_ORDER if c in cautions)
    return Route("soft" if ordered else "none", cautions=ordered)
