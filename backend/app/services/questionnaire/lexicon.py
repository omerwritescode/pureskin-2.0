"""Lexicon-based extraction from the questionnaire's two free-text fields (no LLM).

Text in, tags out: the raw text is never stored, returned or logged. All terms and
matching rules live in questionnaire_config.py.
"""

import re
import unicodedata
from dataclasses import dataclass

from . import questionnaire_config as cfg

# Tag kinds a lexicon term can produce.
ACTIVE, CATEGORY, ALLERGEN, CONDITION, CONCERN = (
    "active", "category", "allergen", "condition", "concern",
)

_CLAUSE_BREAKS = re.compile(cfg.CLAUSE_BREAKS)
_WORD = re.compile(r"[a-z0-9]+")
_NEGATORS = frozenset(cfg.NEGATORS)
_NEGATING_SUFFIXES = frozenset(cfg.NEGATING_SUFFIXES)


def _normalise_token(token: str) -> str:
    if len(token) > cfg.PLURAL_MIN_LENGTH and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _clauses(text: str) -> list[list[str]]:
    text = unicodedata.normalize("NFKC", text).lower().replace("'", "").replace("’", "")
    return [
        [_normalise_token(t) for t in _WORD.findall(clause)]
        for clause in _CLAUSE_BREAKS.split(text)
    ]


def _term_key(term: str) -> tuple[str, ...]:
    (tokens,) = _clauses(term)
    return tuple(tokens)


def _build_table(groups: list[tuple[str, dict[str, tuple[str, ...]]]]) -> dict:
    """{normalised term tokens: {(kind, tag), ...}} from (kind, {tag: terms}) groups."""
    table: dict[tuple[str, ...], set[tuple[str, str]]] = {}
    for kind, terms_by_tag in groups:
        for tag, terms in terms_by_tag.items():
            for term in terms:
                table.setdefault(_term_key(term), set()).add((kind, tag))
    return table


_ACTIVES = {**cfg.ACTIVE_TERMS, cfg.PRESCRIPTION_RETINOID: cfg.PRESCRIPTION_RETINOID_TERMS}

# What each field can mention. Product names can carry concern words ("Acne Control
# Cleanser") and actives; only the sensitivities field names reactions and conditions.
_SENSITIVITIES_TABLE = _build_table([
    (ACTIVE, _ACTIVES),
    (CATEGORY, cfg.CATEGORY_TERMS),
    (ALLERGEN, cfg.ALLERGEN_TERMS),
    (CONDITION, cfg.CONDITION_TERMS),
    (CONCERN, cfg.CONCERN_TERMS),
])
_PRODUCTS_TABLE = _build_table([(ACTIVE, _ACTIVES), (CONCERN, cfg.CONCERN_TERMS)])


def _find(text: str, table: dict) -> set[tuple[str, str]]:
    """Greedy longest-match over each clause, skipping negated matches."""
    longest = max(len(key) for key in table)
    found: set[tuple[str, str]] = set()
    for tokens in _clauses(text):
        i = 0
        while i < len(tokens):
            for length in range(min(longest, len(tokens) - i), 0, -1):
                tags = table.get(tuple(tokens[i:i + length]))
                if tags is None:
                    continue
                negated = (
                    any(t in _NEGATORS for t in tokens[max(0, i - cfg.NEGATION_WINDOW):i])
                    or (i + length < len(tokens) and tokens[i + length] in _NEGATING_SUFFIXES)
                )
                if not negated:
                    found |= tags
                i += length
                break
            else:
                i += 1
    return found


def _tags(found: set[tuple[str, str]], kind: str) -> frozenset[str]:
    return frozenset(tag for k, tag in found if k == kind)


@dataclass(frozen=True)
class SensitivitiesText:
    avoid: frozenset[str]  # categories, allergens and actives to keep out of a routine
    signals: frozenset[str]  # distinct sensitivity signals (rule S4)
    conditions: frozenset[str]
    concerns: frozenset[str]


@dataclass(frozen=True)
class ProductsText:
    actives: frozenset[str]  # catalog ingredient names, plus prescription_retinoid
    concerns: frozenset[str]


def extract_sensitivities(text: str | None) -> SensitivitiesText:
    """Tags from "Any known allergies or sensitivities? Anything else?"."""
    found = _find(text or "", _SENSITIVITIES_TABLE)
    actives = _tags(found, ACTIVE)
    categories = _tags(found, CATEGORY) | {
        cfg.ACTIVE_CATEGORIES[a] for a in actives if a in cfg.ACTIVE_CATEGORIES
    }
    allergens = _tags(found, ALLERGEN)
    conditions = _tags(found, CONDITION)
    # One signal per reaction, keyed by category where there is one, so "glycolic acid"
    # and "salicylic acid" are both the "acids" signal.
    signals = (
        categories
        | allergens
        | {a for a in actives if a not in cfg.ACTIVE_CATEGORIES}
        | ({cfg.CONDITION_SIGNAL} if conditions else set())
    )
    return SensitivitiesText(
        avoid=frozenset(categories | allergens | actives),
        signals=frozenset(signals),
        conditions=conditions,
        concerns=_tags(found, CONCERN),
    )


def extract_products(text: str | None) -> ProductsText:
    """Tags from "Specific products (optional)"."""
    found = _find(text or "", _PRODUCTS_TABLE)
    return ProductsText(actives=_tags(found, ACTIVE), concerns=_tags(found, CONCERN))
