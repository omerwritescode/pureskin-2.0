"""Why a step holds its product: structured facts plus sentences from fixed templates.

Factual about ingredients and the rules only, never efficacy or medical claims: every
sentence comes from recommendation_config.TEMPLATES (a test checks them against a list of
banned words). The rule text describes the rule that actually created the step.
"""

from dataclasses import dataclass

from app.services.ingredients import memberships

from . import recommendation_config as rcfg
from . import routine_config as cfg
from .ranker import band_name
from .rules import BASE


@dataclass(frozen=True)
class WhyTerm:
    """One ingredient's share of the score (all the target groups it matched, summed)."""

    ingredient: str  # as listed on the product
    position: int
    count: int
    target: str  # who asked for the groups it matched, e.g. "redness (High) and sensitive skin"
    contribution: float


@dataclass(frozen=True)
class Why:
    rule: str
    matched: tuple[dict, ...]  # what met the step's keyword: ingredients or label fields
    candidates: int  # eligible products for the step
    rule_order_rank: int  # where the pick stood in rule order (1 = it was the rule-order pick)
    top_terms: tuple[WhyTerm, ...]  # positive contributions only, largest first
    text: tuple[str, ...]


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def phrase(keyword: str, category: str) -> str:
    """How a step's keyword reads: "foaming cleanser", "serum with niacinamide"."""
    template = rcfg.KEYWORD_PHRASES.get(keyword, "{category} with {keyword}")
    return template.format(category=category, keyword=keyword)


def with_article(text: str) -> str:
    return ("an " if text[0].lower() in "aeiou" else "a ") + text


def step_phrase(req) -> str:
    if not req.keywords:
        return req.category
    return " or ".join(phrase(k, req.category) for k in req.keywords)


def rule_text(step, profile, base: str) -> str:
    req = step.req
    t = rcfg.TEMPLATES
    if req.source == BASE:
        text = t["rule_base"].format(skin=base)
    elif req.source in rcfg.SCORE_NAMES:
        score = getattr(profile, req.source)
        text = t["rule_score"].format(
            score_name=rcfg.SCORE_NAMES[req.source], band=band_name(score), score=round(score))
    elif req.source == cfg.SENSITIVE:
        text = t["rule_sensitive"]
    else:  # the core fallback
        text = t["rule_fallback"].format(category=req.category)
    if req.replaces:
        new = " or ".join(with_article(phrase(k, req.category)) for k in req.keywords)
        old = " or ".join(with_article(phrase(k, req.category)) for k in req.replaces)
        text += " " + t["rule_substituted"].format(new=new, old=old)
    return text


def matched(step) -> tuple[tuple[dict, ...], list[str]]:
    """What met the step's keyword, as data and as sentences."""
    keyword = step.matched_keyword
    if keyword is None:
        return (), []
    product = step.product
    items = product.ingredients
    positions = {i.token: i.position for i in items.ingredients}
    names = {i.token: i.name or i.token for i in items.ingredients}
    conditions = cfg.MATCHERS[keyword]
    kinds = {kind for kind, _ in conditions}
    data, text = [], []
    t = rcfg.TEMPLATES
    for kind, value in conditions:
        if kind in ("ingredient", "class"):
            if kind == "ingredient":
                token = value
            else:
                token = memberships(items, strict=False).of(value)[0].token
            data.append({"ingredient": names[token], "position": positions[token], "of": items.count})
            text.append(t["matched_ingredient"].format(
                ingredient=names[token], ordinal=ordinal(positions[token]), count=items.count))
        elif kind == "property":
            data.append({"property": value})
            text.append(t["matched_facial_oil" if value == "anhydrous_oil" else "matched_mineral"])
        elif kind == "texture":
            data.append({"field": "texture", "value": product.texture})
            if "property" not in kinds:  # "facial oil" already says it is an oil
                text.append(t["matched_texture"].format(value=product.texture.replace("_", "-")))
        elif kind == "foaming":
            data.append({"field": "foaming", "value": product.foaming})
            text.append(t["matched_foaming"].format(value=product.foaming.replace("_", "-")))
        elif kind == "min_spf":
            data.append({"field": "spf", "value": product.spf})
            text.append(t["matched_spf"].format(value=product.spf))
    return tuple(data), text


def join_and(items) -> str:
    """"a", "a and b", "a, b and c"."""
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def top_terms(ranked) -> tuple[WhyTerm, ...]:
    """The ingredients with the largest positive contributions, at most TOP_TERMS.

    An ingredient in several target groups (ceramide NP: barrier lipids for dry skin, and
    for sensitive skin) is one entry: its contributions summed, its targets listed once.
    """
    if ranked.scored is None:
        return ()
    merged: dict[str, list] = {}  # token -> [name, position, count, contribution, sources]
    for term in ranked.scored.positive_terms:
        entry = merged.setdefault(term.token, [term.name, term.position, term.count, 0.0, []])
        entry[3] += term.contribution
        entry[4] += [s for s in term.sources if s not in entry[4]]
    best = sorted(merged.values(), key=lambda e: (-e[3], e[1]))[: rcfg.TOP_TERMS]
    return tuple(WhyTerm(name, position, count, join_and(sources), round(total, 3))
                 for name, position, count, total, sources in best)


def terms_text(terms: tuple[WhyTerm, ...]) -> str:
    """ "panthenol (4th of 4 ingredients), matched for redness (High) and sensitive skin; ..." """
    return "; ".join(
        rcfg.TEMPLATES["term"].format(ingredient=t.ingredient, ordinal=ordinal(t.position), count=t.count,
                                      targets=t.target)
        for t in terms
    )


def strong_ingredient(product) -> str:
    """The first strong active a product lists (preservative cutoff), as listed."""
    found = memberships(product.ingredients, strict=False)
    first = min((m for cls in rcfg.STRONG_CLASSES for m in found.of(cls)), key=lambda m: m.position)
    names = {i.token: i.name or i.token for i in product.ingredients.ingredients}
    return names[first.token]


def explain(step, profile, base: str) -> Why:
    t = rcfg.TEMPLATES
    ranking = step.ranking
    pick = ranking.ranked[0]
    data, text = matched(step)
    text = [rule_text(step, profile, base), *text]
    terms = top_terms(pick)
    count = len(ranking.ranked)
    if count == 1:
        what = phrase(step.matched_keyword, step.req.category) if step.matched_keyword else step.req.category
        text.append(t["only_candidate"].format(what=what))
    elif terms:
        text.append(t["ranked_terms"].format(count=count, plural=step.req.category + "s", terms=terms_text(terms)))
    else:
        text.append(t["ranked_no_terms"].format(count=count, plural=step.req.category + "s"))
    rule_pick = ranking.rule_order_pick
    if rule_pick.product.id != pick.product.id:
        # The first sort key that set them apart (the tiers are equal: rule order is keyword order).
        if rule_pick.strong_outside_its_step and not pick.strong_outside_its_step:
            text.append(t["strong_demoted"].format(
                other=rule_pick.product.name, ingredient=strong_ingredient(rule_pick.product)))
        elif rule_pick.clashes_with and not pick.clashes_with:
            text.append(t["conflict_safe"].format(other=rule_pick.product.name, earlier=rule_pick.clashes_with))
    rank = next(i for i, r in enumerate(ranking.rule_order, 1) if r.product.id == pick.product.id)
    return Why(text[0], data, count, rank, terms, tuple(text))


def explain_alternative(ranked) -> str:
    terms = top_terms(ranked)
    if terms:
        return rcfg.TEMPLATES["alternative_terms"].format(name=ranked.product.name, terms=terms_text(terms))
    return rcfg.TEMPLATES["alternative_no_terms"].format(name=ranked.product.name)
