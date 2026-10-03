"""Does a product satisfy a routine keyword? (routine_config.MATCHERS)

Since 7c-i (b) a keyword is never matched against a product's description: it is a set
of conditions on the ingredient list (whole canonical tokens, classes, derived
properties) and on the labelled format fields (texture, foaming, SPF).
"""

from app.services.ingredients import anhydrous_oil, in_class, mineral_only

from . import routine_config as cfg

PROPERTIES = {"anhydrous_oil": anhydrous_oil, "mineral_only": mineral_only}


def condition_holds(product, kind: str, value) -> bool:
    if kind == "ingredient":
        return value in product.ingredients.tokens
    if kind == "class":
        return in_class(product.ingredients, value, strict=False)
    if kind == "property":
        return PROPERTIES[value](product.ingredients)
    if kind == "texture":
        return product.texture in value
    if kind == "foaming":
        return product.foaming in value
    if kind == "min_spf":
        return product.spf is not None and product.spf >= value
    raise ValueError(f"Unknown matcher condition {kind!r}")


def keyword_matches(product, keyword: str) -> bool:
    return all(condition_holds(product, kind, value) for kind, value in cfg.MATCHERS[keyword])
