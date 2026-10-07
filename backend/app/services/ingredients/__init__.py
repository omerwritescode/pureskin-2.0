"""Shared ingredient normaliser and vocabulary (roadmap step 7c).

One normaliser for every ingredient decision: routine rules, conflict checks, the ranker
and the catalog loader. Public interface:

    split_inci(text) -> list[str]                    an INCI string -> ingredient names
    canonical(name) -> str                            one name -> its canonical token
    normalise_ingredients(names) -> NormalisedIngredients
    memberships(items, strict=...) -> Memberships    the one class-membership rule
    fragrance_free / mineral_only / anhydrous_oil    properties an ingredient list gives
    clean_ingredient_text(text, directives) -> Cleaned   page text -> names (7c-iii)
    INGREDIENT_CONFIG_VERSION

See README.md. Run the review report with:  python -m app.services.ingredients.review
"""

from .clean import Cleaned, CleaningError, Directives, clean_ingredient_text, directives
from .ingredient_config import CLASS_PREFIX, INGREDIENT_CONFIG_VERSION
from .membership import Dismissal, Membership, Memberships, cutoff, in_class, memberships
from .normalise import (
    Ingredient,
    InvalidIngredientName,
    NormalisedIngredients,
    canonical,
    check_conflict_name,
    is_known,
    normalise_ingredients,
    split_inci,
)
from .properties import anhydrous_oil, fragrance_free, fragrance_tokens, mineral_only

__all__ = [
    "CLASS_PREFIX",
    "INGREDIENT_CONFIG_VERSION",
    "Cleaned",
    "CleaningError",
    "Directives",
    "Dismissal",
    "Ingredient",
    "InvalidIngredientName",
    "Membership",
    "Memberships",
    "NormalisedIngredients",
    "anhydrous_oil",
    "canonical",
    "check_conflict_name",
    "clean_ingredient_text",
    "cutoff",
    "directives",
    "fragrance_free",
    "fragrance_tokens",
    "in_class",
    "is_known",
    "memberships",
    "mineral_only",
    "normalise_ingredients",
    "split_inci",
]
