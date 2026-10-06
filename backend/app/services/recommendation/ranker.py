"""Score the products a rule step made eligible: content-based, ingredient-level TF-IDF.

Pure. The ranker never decides eligibility: the engine applies every hard rule first and
hands it the eligible products only, and the ordering it returns is a permutation of them.

    score(p) = sum over target groups g of weight(g) * max over p's ingredients t in g of x_p(t)

x_p(t) is the TF-IDF value (tfidf.py). A group applies only to the categories it lists
(recommendation_config.TARGET_GROUPS). A weighted dot product, not cosine: cosine would
divide by the product's vector length, so a complete 30-ingredient label would lose to a
5-ingredient one with the same actives, and it can't express penalties. Taking the max
within a group means listing several members of one group earns no extra credit.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from app.services.ingredients import CLASS_PREFIX, memberships
from app.services.skin_profile.skin_profile_config import SCORE_BANDS

from . import recommendation_config as cfg
from .rules import base_set
from .tfidf import idf_table, values


@dataclass(frozen=True)
class Target:
    group: str
    weight: float
    sources: tuple[str, ...]  # who asked for it, e.g. "oily skin", "redness (High)"


@dataclass(frozen=True)
class Term:
    """One target group's contribution to a product's score."""

    group: str
    token: str  # the ingredient that gave the group its value
    name: str  # that ingredient as listed on the product
    position: int
    count: int  # ingredients in the product's list
    contribution: float
    sources: tuple[str, ...]


@dataclass(frozen=True)
class Scored:
    score: float
    terms: tuple[Term, ...]  # every non-zero contribution, largest first

    @property
    def positive_terms(self) -> tuple[Term, ...]:
        return tuple(t for t in self.terms if t.contribution > 0)


def band_name(score: float) -> str:
    value = round(score)
    for name, low, high in SCORE_BANDS:
        if low <= value <= high:
            return name
    raise ValueError(f"score {score} is outside every band")


def stated_concern_score(profile) -> str | None:
    tags = getattr(profile, "questionnaire_tags", None)
    stated = tags.get("stated_concern") if tags else None
    return cfg.STATED_CONCERN_SCORES.get(stated)


def targets(profile) -> dict[str, Target]:
    """The profile's target groups and their summed weights (zero-weight groups dropped)."""
    weights: dict[str, float] = {}
    sources: dict[str, list[str]] = {}

    def add(group: str, weight: float, source: str) -> None:
        weights[group] = weights.get(group, 0.0) + weight
        sources.setdefault(group, []).append(source)

    skin = base_set(profile)
    for group, weight in cfg.SKIN_TYPE_TARGETS.get(skin, ()):
        add(group, weight, cfg.TARGET_SOURCE_NAMES["skin"].format(skin=skin))
    goal = stated_concern_score(profile)
    for score, groups in cfg.CONCERN_TARGETS.items():
        band = band_name(getattr(profile, score))
        scale = cfg.BAND_SCALE[band]
        if scale == 0:
            continue
        multiplier = cfg.STATED_CONCERN_MULTIPLIER if score == goal else 1.0
        label = cfg.TARGET_SOURCE_NAMES["goal" if score == goal else "concern"].format(
            concern=cfg.CONCERN_NAMES[score], band=band)
        for group, weight in groups:
            add(group, weight * scale * multiplier, label)
    if profile.is_sensitive:
        for group, weight in cfg.SENSITIVE_TARGETS:
            add(group, weight, cfg.TARGET_SOURCE_NAMES["sensitive"])
    return {
        group: Target(group, weight, tuple(dict.fromkeys(sources[group])))
        for group, weight in weights.items() if weight != 0
    }


class Scorer:
    """Scores products for one profile against one catalog (the IDF corpus)."""

    def __init__(self, profile, catalog: Iterable) -> None:
        catalog = list(catalog)
        self.targets = targets(profile)
        self.n = len(catalog)
        self.idf = idf_table(p.ingredients for p in catalog)
        self._cache: dict[int, Scored] = {}

    def score(self, product) -> Scored:
        cached = self._cache.get(product.id)
        if cached is None:
            cached = self._cache[product.id] = self._score(product)
        return cached

    def _score(self, product) -> Scored:
        items = product.ingredients
        x = values(items, self.idf, self.n)
        positions = {i.token: i.position for i in items.ingredients}
        names = {i.token: i.name or i.token for i in items.ingredients}
        found = memberships(items, strict=False)
        terms = []
        for group, target in self.targets.items():
            members, categories = cfg.TARGET_GROUPS[group]
            if categories is not None and product.category not in categories:
                continue
            tokens = set()
            for key in members:
                if key.startswith(CLASS_PREFIX):
                    tokens |= {m.token for m in found.of(key.removeprefix(CLASS_PREFIX))}
                elif key in positions:
                    tokens.add(key)
            if not tokens:
                continue
            # The highest value in the group; on a tie, the earlier ingredient.
            token = min(tokens, key=lambda t: (-x[t], positions[t], t))
            terms.append(Term(group, token, names[token], positions[token], items.count,
                              target.weight * x[token], target.sources))
        terms.sort(key=lambda t: (-t.contribution, t.group))
        return Scored(round(sum(t.contribution for t in terms), cfg.SCORE_DECIMALS), tuple(terms))
