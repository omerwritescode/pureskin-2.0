"""Which classes a product's ingredients belong to: the one shared membership function.

Every class decision (routine keywords, conflicts, strong actives, session rules, the
avoid list) goes through memberships(), so they all apply the same rule:

- A non-ambiguous member always counts toward its class.
- An AMBIGUOUS member (ingredient_config.AMBIGUOUS_MEMBERS) counts only if it appears
  at or before the first recognised preservative (the cutoff), a proxy for the ~1% line.
  With no recognised preservative, it counts. An ambiguous member is never the cutoff.
- strict=True ignores the cutoff (every member counts). The avoid list is strict;
  conflicts, strong-active suppression and session rules use the cutoff.

`strict` has no default on purpose: every caller states which rule it applies.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from . import ingredient_config as cfg
from .normalise import TOKEN_CLASSES, Ingredient, NormalisedIngredients

_AMBIGUOUS = frozenset((cls, token) for cls, tokens in cfg.AMBIGUOUS_MEMBERS.items() for token in tokens)
_AMBIGUOUS_TOKENS = frozenset(token for _, token in _AMBIGUOUS)
_PRESERVATIVES = frozenset(cfg.PRESERVATIVES)


@dataclass(frozen=True)
class Membership:
    token: str
    cls: str
    position: int


@dataclass(frozen=True)
class Dismissal:
    """An ambiguous membership the cutoff left out."""

    token: str
    cls: str
    position: int
    cutoff: str
    cutoff_position: int


@dataclass(frozen=True)
class Memberships:
    counted: tuple[Membership, ...]
    dismissed: tuple[Dismissal, ...]

    @property
    def classes(self) -> frozenset[str]:
        return frozenset(m.cls for m in self.counted)

    def of(self, cls: str) -> tuple[Membership, ...]:
        return tuple(m for m in self.counted if m.cls == cls)

    def __contains__(self, cls: str) -> bool:
        return any(m.cls == cls for m in self.counted)


def _ingredients(items: NormalisedIngredients | Sequence[Ingredient]) -> Sequence[Ingredient]:
    return items.ingredients if isinstance(items, NormalisedIngredients) else items


def cutoff(items: NormalisedIngredients | Sequence[Ingredient]) -> Ingredient | None:
    """The first recognised preservative that isn't itself an ambiguous member."""
    for ingredient in _ingredients(items):
        if ingredient.token in _PRESERVATIVES and ingredient.token not in _AMBIGUOUS_TOKENS:
            return ingredient
    return None


def memberships(items: NormalisedIngredients | Sequence[Ingredient], *, strict: bool) -> Memberships:
    ingredients = _ingredients(items)
    limit = None if strict else cutoff(ingredients)
    counted, dismissed = [], []
    for ingredient in ingredients:
        for cls in sorted(TOKEN_CLASSES.get(ingredient.token, ())):
            if limit is not None and (cls, ingredient.token) in _AMBIGUOUS and ingredient.position > limit.position:
                dismissed.append(Dismissal(ingredient.token, cls, ingredient.position, limit.token, limit.position))
            else:
                counted.append(Membership(ingredient.token, cls, ingredient.position))
    return Memberships(tuple(counted), tuple(dismissed))


def in_class(items: NormalisedIngredients | Sequence[Ingredient], cls: str, *, strict: bool) -> bool:
    return cls in memberships(items, strict=strict)
