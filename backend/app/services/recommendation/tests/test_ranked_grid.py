"""Hard invariants of the ranked routine over the whole grid, with and without tags.

The grids are test_engine.GRID (2,430 profiles) and test_current_products.GRID (3,072
profiles x tag scenarios), built in RANKED mode (the default). The ranker only orders
what the rules made eligible, so every safety invariant of 7c-i must still hold; the
conflict, sensitive-skin and morning-session invariants in those two files run on the
same ranked routines.
"""

import hashlib
import itertools
import json
import random

from app.services.recommendation import recommendation_config as rcfg
from app.services.recommendation import routine_config as cfg
from app.services.recommendation.engine import (
    RULE_ORDER,
    build_routine,
    candidates,
    current_use,
    current_use_exclusion,
    exclusion,
    find_conflict,
    kept_in_order,
    step_targets_strong,
)
from app.services.recommendation.explain import explain
from app.services.recommendation.tests import test_current_products as tc
from app.services.recommendation.tests import test_engine as te

CATALOG = sorted(te.SEED_PRODUCTS, key=lambda p: p.id)
CONFLICTS = te.SEED_CONFLICTS
CASES = [(p, r) for p, r in te.ROUTINES] + [(p, r) for _, p, r in tc.ROUTINES]


def sessions(routine):
    return ((cfg.AM, routine.am), (cfg.PM, routine.pm))


def test_the_grid_covers_both_files():
    assert len(CASES) == 2430 + 3072


def test_the_ranked_set_is_the_eligible_set():
    """Every ranked product passes every hard rule, and every eligible product is ranked
    unless another step of the session already holds it."""
    for p, routine in CASES:
        current = current_use(p)
        for session, steps in sessions(routine):
            for step in steps:
                ranked = [r.product.id for r in step.ranking.ranked]
                assert len(ranked) == len(set(ranked))
                assert sorted(ranked) == sorted(r.product.id for r in step.ranking.rule_order)
                assert step.product.id == ranked[0]
                eligible = {
                    product.id for product, _ in candidates(CATALOG, step.req)
                    if exclusion(p, product, session, current, CONFLICTS) is None
                }
                held_elsewhere = {s.product.id for s in steps if s is not step}
                assert set(ranked) <= eligible
                assert eligible - set(ranked) <= held_elsewhere


def test_the_sort_keys_hold_for_every_pick():
    """Tier, then strong actives outside their step last, then conflict-safe, then score."""
    for _, routine in CASES:
        for _, steps in sessions(routine):
            for step in steps:
                pick, *rest = step.ranking.ranked
                for other in rest:
                    assert pick.tier <= other.tier
                    if other.tier != pick.tier:
                        continue
                    assert pick.strong_outside_its_step <= other.strong_outside_its_step
                    if other.strong_outside_its_step != pick.strong_outside_its_step:
                        continue
                    assert (pick.clashes_with is not None) <= (other.clashes_with is not None)
                    if (pick.clashes_with is None) != (other.clashes_with is None):
                        continue
                    assert pick.score >= other.score
                    if pick.score == other.score:
                        assert pick.position < other.position


def test_strong_actives_enter_only_through_a_step_that_targets_them():
    for _, routine in CASES:
        for _, steps in sessions(routine):
            for step in kept_in_order(steps):
                if step_targets_strong(step.req):
                    continue
                pick = step.ranking.ranked[0]
                if pick.strong_outside_its_step:  # only when every product of its tier has one
                    assert all(r.strong_outside_its_step for r in step.ranking.ranked if r.tier == pick.tier)


def test_no_kept_product_conflicts_with_another_in_its_session():
    for _, routine in CASES:
        for _, steps in sessions(routine):
            for a, b in itertools.combinations(kept_in_order(steps), 2):
                if a.req.category in cfg.CORE_CATEGORIES and b.req.category in cfg.CORE_CATEGORIES:
                    continue  # two core products are kept with a warning (7c-i)
                assert find_conflict(a.product, b.product, CONFLICTS) is None


def test_alternatives_are_safe_swaps():
    for p, routine in CASES:
        current = current_use(p)
        for session, steps in sessions(routine):
            kept = kept_in_order(steps)
            for step in kept:
                assert len(step.alternatives) <= rcfg.MAX_ALTERNATIVES
                others = [s.product for s in kept if s is not step]
                ranked = [r.product.id for r in step.ranking.ranked]
                ids = [a.product.id for a in step.alternatives]
                assert ids == sorted(ids, key=ranked.index)  # in ranking order
                for alt in step.alternatives:
                    assert alt.product.id != step.product.id
                    assert alt.product.id not in {o.id for o in others}
                    assert exclusion(p, alt.product, session, current, CONFLICTS) is None
                    for other in others:
                        assert find_conflict(alt.product, other, CONFLICTS) is None


def test_no_avoided_ingredient_or_active_in_use_conflict_in_any_ranking():
    for p, routine in CASES:
        current = current_use(p)
        if current is None:
            continue
        for _, steps in sessions(routine):
            for step in steps:
                for r in step.ranking.ranked:
                    assert current_use_exclusion(current, r.product, CONFLICTS) is None


def fingerprint(p, routine):
    out = []
    for _, steps in sessions(routine):
        for step in steps:
            out.append((
                step.req, step.removed, [r.product.id for r in step.ranking.ranked],
                [a.product.id for a in step.alternatives], explain(step, p, routine.base_set).text,
            ))
    return out, routine.warnings, routine.left_out


def test_the_ranked_routine_is_deterministic_and_ignores_catalog_order():
    shuffled = CATALOG[:]
    random.Random(11).shuffle(shuffled)
    for p, routine in CASES:
        again = build_routine(p, shuffled, CONFLICTS)
        assert fingerprint(p, again) == fingerprint(p, routine)


# --------------------------------------------------------------------------------------
# RULE_ORDER reproduces 7c-i (the evaluation baseline)
# --------------------------------------------------------------------------------------

# Recorded from 7c-i's choices with routine-2.2.0's texts (2.2.0 only reworded the
# low-severity note). It covers the picks, warnings and left-out reasons of both grids.
# If a routine rule changes on purpose, re-record it and say why in the commit message.
RULE_ORDER_DIGEST = "29fa0ecb8f7b3c29"


def summary(r):
    s = lambda steps: [(x.req.category, x.product.id, x.matched_keyword) for x in kept_in_order(steps)]
    left_out = [(lo.product_id, list(lo.sessions), lo.reason, lo.code, lo.severity) for lo in r.left_out]
    return [r.base_set, s(r.am), s(r.pm), r.warnings, left_out, r.current_products_considered]


def test_rule_order_mode_reproduces_the_7c_i_routines():
    profiles = [p for p, _ in te.ROUTINES] + [p for _, p, _ in tc.ROUTINES]
    out = [summary(build_routine(p, te.SEED_PRODUCTS, CONFLICTS, RULE_ORDER)) for p in profiles]
    digest = hashlib.sha256(json.dumps(out, sort_keys=True).encode()).hexdigest()[:16]
    assert digest == RULE_ORDER_DIGEST
