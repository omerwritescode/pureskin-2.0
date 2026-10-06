"""Ingredient-level TF-IDF with a list-position decay, in plain Python.

    position weight  w(r)  = 1 / log2(r + 1)          r = 1-based position in the list
    inverse doc freq idf(t) = ln((1 + N) / (1 + df(t))) + 1   over the whole catalog
    value            x_p(t) = w(r_p(t)) * idf(t)       r_p(t) = t's first position in p

INCI lists run from the highest concentration down (to about 1%), so an earlier ingredient
weighs more; the decay is gentle because potent actives work below 1%. IDF is smoothed
(never zero, finite for any token). Tokens are canonical ingredient tokens
(app.services.ingredients), one per ingredient, so a product listing an ingredient twice
(or under two synonyms) counts it once, at its first position.
"""

import math
from collections import Counter
from collections.abc import Iterable

from app.services.ingredients import NormalisedIngredients


def position_weight(position: int) -> float:
    return 1.0 / math.log2(position + 1)


def idf_table(products: Iterable[NormalisedIngredients]) -> dict[str, float]:
    """Smoothed IDF for every token in the corpus."""
    lists = list(products)
    n = len(lists)
    df = Counter(token for items in lists for token in set(items.tokens))
    return {token: math.log((1 + n) / (1 + count)) + 1 for token, count in df.items()}


def idf(table: dict[str, float], n: int, token: str) -> float:
    """IDF of a token, also for one the corpus doesn't contain (df = 0)."""
    return table.get(token, math.log(1 + n) + 1)


def values(items: NormalisedIngredients, table: dict[str, float], n: int) -> dict[str, float]:
    """x_p(t) for every token of one product."""
    return {i.token: position_weight(i.position) * idf(table, n, i.token) for i in items.ingredients}
