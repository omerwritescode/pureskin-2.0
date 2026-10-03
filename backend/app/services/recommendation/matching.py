"""Does a product satisfy a routine keyword? Whole tokens only, never substrings.

Step 6 semantics, kept: a keyword matches a product's ingredients OR its description.
- Ingredients: the keyword's canonical token (or class) from INGREDIENT_KEYWORDS, via the
  shared normaliser and membership rule. "peptide" matches palmitoyl pentapeptide-4
  because it is in the peptide class, not because one string contains the other.
- Description: the keyword's words as a whole-word phrase, not preceded by a negator,
  so "Non-foaming cream cleanser" is a cream cleanser but not a foaming one.
"""

import re
import unicodedata
from functools import lru_cache

from app.services.ingredients import CLASS_PREFIX, in_class

from . import routine_config as cfg

_WORD = re.compile(r"[a-z0-9]+")
_NEGATORS = frozenset(cfg.DESCRIPTION_NEGATORS)


@lru_cache(maxsize=4096)
def words(text: str) -> tuple[str, ...]:
    return tuple(_WORD.findall(unicodedata.normalize("NFKC", text).lower()))


def ingredient_matches(product, keyword: str) -> bool:
    target = cfg.INGREDIENT_KEYWORDS.get(keyword)
    if target is None:
        return False
    if target.startswith(CLASS_PREFIX):
        return in_class(product.ingredients, target.removeprefix(CLASS_PREFIX), strict=False)
    return target in product.ingredients.tokens


def description_matches(description: str | None, keyword: str) -> bool:
    if not description:
        return False
    text, phrase = words(description), words(keyword)
    n = len(phrase)
    return any(
        text[i:i + n] == phrase and (i == 0 or text[i - 1] not in _NEGATORS)
        for i in range(len(text) - n + 1)
    )


def keyword_matches(product, keyword: str) -> bool:
    return ingredient_matches(product, keyword) or description_matches(product.description, keyword)
