"""Product properties that an ingredient list gives reliably.

Only these are derived from ingredients. Texture and foaming can't be read off a real
INCI list, so they are product fields filled at seed time (step 7c-i b), not derived here.
An unknown token never makes a property true: callers exclude products with unknown
ingredients anyway (fail closed).
"""

from . import ingredient_config as cfg
from .membership import memberships
from .normalise import NormalisedIngredients


def fragrance_tokens(items: NormalisedIngredients) -> tuple[str, ...]:
    """Ingredients that make a product not fragrance-free: declared fragrance, declared
    fragrance allergens (benzyl alcohol included) and essential oils. Strict: the
    preservative cutoff never hides one."""
    found = memberships(items, strict=True)
    return tuple(dict.fromkeys(m.token for cls in cfg.FRAGRANCE_CLASSES for m in found.of(cls)))


def fragrance_free(items: NormalisedIngredients) -> bool:
    """No declared fragrance. (An undeclared fragrance component can't be seen.)"""
    return not fragrance_tokens(items)


def mineral_only(items: NormalisedIngredients) -> bool:
    """At least one mineral UV filter and no organic one."""
    found = memberships(items, strict=True)
    return "uv_mineral" in found and "uv_organic" not in found


def anhydrous_oil(items: NormalisedIngredients) -> bool:
    """A facial oil: no water-phase ingredient anywhere, and the first ingredient is an oil."""
    found = memberships(items, strict=True)
    if not items.ingredients or "water_phase" in found:
        return False
    first = items.ingredients[0]
    return first.position == 1 and any(m.token == first.token for m in found.of("oil"))
