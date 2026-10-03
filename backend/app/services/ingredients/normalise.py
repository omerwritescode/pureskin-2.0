"""Ingredient names -> canonical tokens. One token per ingredient, never per word.

Pure: no I/O, no logging. Every rule and list lives in ingredient_config.py.

    split_inci("Water (Aqua, Eau), 1,2-Hexanediol")  -> ["Water (Aqua, Eau)", "1,2-Hexanediol"]
    canonical("CI 77891 (Titanium Dioxide)")         -> "titanium dioxide"
    normalise_ingredients(["Aqua", "Niacinamide 10%"]).tokens -> ("water", "niacinamide")

Names that can't be cleaned safely (a ":" or a non-ASCII character) raise
InvalidIngredientName, and names outside the vocabulary are reported as unknown, so
callers can fail closed instead of guessing.
"""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from . import ingredient_config as cfg

_MARKERS = str.maketrans("", "", cfg.MARKERS)
_PUNCTUATION = str.maketrans({**dict.fromkeys(cfg.DASHES, "-"), **dict.fromkeys(cfg.APOSTROPHES, "'")})
_PERCENT = re.compile(cfg.PERCENT)
_INNER_BRACKETS = re.compile(r"\(([^()\[\]]*)\)|\[([^()\[\]]*)\]")
_ALLOWED = re.compile(cfg.ALLOWED_NAME)

TOKEN_CLASSES: dict[str, frozenset[str]] = {}
for _cls, _members in cfg.CLASSES.items():
    for _token in _members:
        TOKEN_CLASSES[_token] = TOKEN_CLASSES.get(_token, frozenset()) | {_cls}

# Every canonical token the vocabulary knows. Synonym targets must be in here too
# (tests/test_vocabulary.py), so a synonym can never lead to an unknown token.
KNOWN: frozenset[str] = frozenset(TOKEN_CLASSES) | frozenset(cfg.NEUTRAL) | frozenset(cfg.PRESERVATIVES)


class InvalidIngredientName(ValueError):
    """The name contains something the vocabulary never allows (":" or non-ASCII)."""


@dataclass(frozen=True)
class Ingredient:
    token: str  # canonical
    position: int  # 1-based position in the original list (its first occurrence)


@dataclass(frozen=True)
class NormalisedIngredients:
    ingredients: tuple[Ingredient, ...]  # one per token, in list order
    unknown: tuple[str, ...] = ()  # tokens outside the vocabulary (also in ingredients)
    invalid: tuple[str, ...] = ()  # names that failed cleaning (left out of ingredients)

    @property
    def tokens(self) -> tuple[str, ...]:
        return tuple(i.token for i in self.ingredients)

    @property
    def fully_known(self) -> bool:
        return not self.unknown and not self.invalid


def split_inci(text: str) -> list[str]:
    """Split an INCI list on commas, but not inside brackets or between digits.

    "Water (Aqua, Eau)" and "1,2-Hexanediol" each stay one ingredient. Never splits on
    whitespace.
    """
    items, current, depth = [], [], 0
    for i, char in enumerate(text):
        if char in "([":
            depth += 1
        elif char in ")]":
            depth = max(0, depth - 1)
        between_digits = 0 < i < len(text) - 1 and text[i - 1].isdigit() and text[i + 1].isdigit()
        if char == "," and depth == 0 and not between_digits:
            items.append("".join(current))
            current = []
        else:
            current.append(char)
    items.append("".join(current))
    return [item.strip() for item in items if item.strip(" .;\t\n")]


def _tidy(text: str) -> str:
    return " ".join(text.split()).strip(" .,;")


def clean(raw: str) -> tuple[str, tuple[str, ...]]:
    """(the cleaned name, the cleaned contents of its brackets).

    Footnote marks, percentages and bracketed text are removed; case, dashes,
    apostrophes and spacing are unified. Raises InvalidIngredientName if what is left
    contains anything but lowercase ASCII letters, digits and  ,'./+-
    """
    text = unicodedata.normalize("NFKC", raw.translate(_MARKERS)).lower().translate(_PUNCTUATION)
    text = _PERCENT.sub("", text)
    brackets = []
    while match := _INNER_BRACKETS.search(text):  # innermost first, so nesting works
        brackets.append(_tidy(match.group(1) if match.group(1) is not None else match.group(2)))
        text = text[: match.start()] + " " + text[match.end():]
    name = _tidy(text)
    if not _ALLOWED.fullmatch(name):
        raise InvalidIngredientName(f"Can't normalise ingredient name {raw!r}")
    return name, tuple(b for b in brackets if _ALLOWED.fullmatch(b))


def canonical(raw: str) -> str:
    """The canonical token for one ingredient name (possibly an unknown one).

    A bracket's content is used only when the name itself is unknown, e.g.
    "Sodium Hyaluronate (Hyaluronic Acid)" is decided by its outer name.
    """
    name, brackets = clean(raw)
    token = cfg.SYNONYMS.get(name, name)
    if token in KNOWN:
        return token
    for alias in brackets:
        alias_token = cfg.SYNONYMS.get(alias, alias)
        if alias_token in KNOWN:
            return alias_token
    return token


def normalise_ingredients(raw_names: Iterable[str]) -> NormalisedIngredients:
    """Canonical tokens for an ingredient list, keeping each token's first position."""
    ingredients, unknown, invalid, seen = [], [], [], set()
    for position, raw in enumerate(raw_names, start=1):
        try:
            token = canonical(raw)
        except InvalidIngredientName:
            invalid.append(raw)
            continue
        if token in seen:
            continue
        seen.add(token)
        ingredients.append(Ingredient(token, position))
        if token not in KNOWN:
            unknown.append(token)
    return NormalisedIngredients(tuple(ingredients), tuple(unknown), tuple(invalid))


def is_known(token: str) -> bool:
    return token in KNOWN


def check_conflict_name(name: str) -> None:
    """A conflict-table name must be "class:<a known class>" or a known canonical token.

    Raises ValueError otherwise, so a typo can't create a rule that silently never fires.
    """
    if name.startswith(cfg.CLASS_PREFIX):
        cls = name.removeprefix(cfg.CLASS_PREFIX)
        if not re.fullmatch(cfg.CLASS_NAME, cls) or cls not in cfg.CLASSES:
            raise ValueError(f"Unknown ingredient class in conflict rule: {name!r}")
        return
    if canonical(name) != name or name not in KNOWN:
        raise ValueError(f"Conflict rule names {name!r}, which isn't a known canonical ingredient")
