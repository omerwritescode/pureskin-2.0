"""Step 7c-i (a) changed HOW keywords match, not WHAT the routine picks. Proof:

1. The step 6 matcher (SQL ILIKE '%keyword%' on the joined ingredient list OR the
   description) is reimplemented here as LEGACY. Over every profile in a grid, the
   routine built with LEGACY and with the new whole-token matcher is identical:
   same products, keywords, removals and warnings.
2. Where the two matchers disagree on a single (keyword, product) pair, the
   disagreement is exactly the documented list below, and none of it changes a pick.

The recorded snapshots (app/tests/test_routine_behaviour.py) prove the same end to end
through the database.
"""

import itertools
from types import SimpleNamespace

import pytest

import seed
from app.services.recommendation import engine, routine_config as cfg
from app.services.recommendation.matching import keyword_matches

SCORES = ("acne_score", "redness_score", "wrinkle_score", "pigmentation_score", "pore_score")
SKIN_TYPES = ("oily", "dry", "combination", "normal", None, "unknown")
LEVELS = (15, 45, 75)  # Low, Moderate (above the combination rule's 40), High

# Products get ids in seed order, as a freshly seeded database assigns them.
RAW = {i: (ingredients, description) for i, (_n, _b, _c, description, ingredients) in enumerate(seed.PRODUCTS, 1)}
PRODUCTS = [
    engine.product_record(i, name, category, description, ingredients)
    for i, (name, _brand, category, description, ingredients) in enumerate(seed.PRODUCTS, 1)
]
CONFLICTS = engine.conflict_table((a, b, severity, reason) for a, b, severity, reason in seed.CONFLICTS)


def legacy_matches(product, keyword: str) -> bool:
    """Step 6: ILIKE '%keyword%' on array_to_string(ingredients, '|') OR description."""
    ingredients, description = RAW[product.id]
    k = keyword.lower()
    return k in "|".join(ingredients).lower() or k in (description or "").lower()


def profiles():
    for skin_type, sensitive, levels in itertools.product(SKIN_TYPES, (False, True), itertools.product(LEVELS, repeat=5)):
        yield SimpleNamespace(skin_type=skin_type, is_sensitive=sensitive, **dict(zip(SCORES, levels)))


def summary(routine: engine.Routine):
    def steps(session):
        return [
            (s.req.category, s.req.keywords, s.req.sessions, s.product.id, s.matched_keyword, s.removed)
            for s in session
        ]

    return routine.base_set, steps(routine.am), steps(routine.pm), routine.warnings


def test_the_routine_is_identical_under_the_old_and_new_matchers(monkeypatch):
    profile_list = list(profiles())
    new = [summary(engine.build_routine(p, PRODUCTS, CONFLICTS)) for p in profile_list]
    monkeypatch.setattr(engine, "keyword_matches", legacy_matches)
    old = [summary(engine.build_routine(p, PRODUCTS, CONFLICTS)) for p in profile_list]

    assert len(profile_list) == 2916
    differing = [(p, o, n) for p, o, n in zip(profile_list, old, new) if o != n]
    assert differing == []


def keyword_slots() -> set[tuple[str, str]]:
    """Every (category, keyword) a routine rule uses."""
    steps = [s for steps in cfg.BASE_STEPS.values() for s in steps]
    steps += [s for _, score_steps in cfg.SCORE_STEPS for s in score_steps]
    steps.append(cfg.COMBINATION_RETINOL_STEP)
    return {(category, keyword) for category, keywords, _, _ in steps for keyword in keywords}


# (keyword, product, legacy result, new result): every pair where the matchers disagree.
EXPECTED_DISAGREEMENTS = {
    # "Non-foaming cream cleanser": a substring false positive, now fixed. Never picked:
    # "oil-free" is tried first and Clear Balance (lower id) matches it.
    ("foaming", "Hydra Cream Cleanser", True, False),
    # Sodium hyaluronate is hyaluronic acid's salt. Never picked: the Hyaluronic Acid 2% +
    # B5 Serum has a lower id and matches too.
    ("hyaluronic acid", "Alpha Arbutin 2% + HA Serum", False, True),
}


def test_single_keyword_disagreements_are_exactly_the_documented_ones():
    found = set()
    for category, keyword in keyword_slots():
        for product in PRODUCTS:
            if product.category != category:
                continue
            old, new = legacy_matches(product, keyword), keyword_matches(product, keyword)
            if old != new:
                found.add((keyword, product.name, old, new))
    assert found == EXPECTED_DISAGREEMENTS


@pytest.mark.parametrize("category, keyword", sorted(keyword_slots()))
def test_every_keyword_still_matches_some_product(category, keyword):
    assert any(keyword_matches(p, keyword) for p in PRODUCTS if p.category == category)
