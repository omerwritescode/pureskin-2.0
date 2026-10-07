"""The routine engine on the real catalog (backend/catalog/products.json, step 7c-iii).

The safety invariants over both grids (test_engine.GRID: 2,430 profiles without tags;
test_current_products.GRID: 3,072 profiles x current-product/avoid scenarios), and a
recorded snapshot of a few routines (app/tests/snapshots/routine_real_catalog.json). The
snapshot is what the code did on this catalog, not a specification: a change to it must be
deliberate and reviewed. Nothing here measures whether a routine is good for anyone's skin.
"""

import itertools
import random
from types import SimpleNamespace

import pytest


import seed
from app.services.catalog import load_catalog, product_records
from app.services.ingredients import fragrance_tokens, in_class, memberships
from app.services.recommendation import routine_config as cfg
from app.services.recommendation.engine import (
    build_routine,
    candidates,
    conflict_table,
    current_use,
    current_use_exclusion,
    exclusion,
    find_conflict,
    kept_in_order,
)
from app.services.recommendation.explain import explain
from app.services.recommendation.tests import test_current_products as tc
from app.services.recommendation.tests import test_engine as te
from app.tests.snapshot import check_snapshot

CATALOG = product_records(load_catalog())
CONFLICTS = conflict_table(seed.CONFLICTS)
PROFILES = [p for p in te.GRID] + [p for _, p in tc.GRID]


@pytest.fixture(scope="module")
def routines():
    """Every grid profile's routine on the real catalog (built once; a few minutes)."""
    return [(p, build_routine(p, CATALOG, CONFLICTS)) for p in PROFILES]


def sessions(routine):
    return ((cfg.AM, routine.am), (cfg.PM, routine.pm))


def test_the_grids_and_the_catalog(routines):
    assert len(CATALOG) == 37 and len(routines) == 2430 + 3072


def test_the_ranked_set_is_the_eligible_set(routines):
    for p, routine in routines:
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


def test_no_two_products_in_a_session_conflict(routines):
    """Stricter than the fixture grid: not even two core products clash on this catalog."""
    for _, routine in routines:
        for _, steps in sessions(routine):
            for a, b in itertools.combinations(kept_in_order(steps), 2):
                assert find_conflict(a.product, b.product, CONFLICTS) is None, (a.product.name, b.product.name)


def test_sensitive_skin_gets_no_strong_active_l_ascorbic_acid_or_fragrance(routines):
    for p, routine in routines:
        if not p.is_sensitive:
            continue
        for _, steps in sessions(routine):
            for step in kept_in_order(steps):
                items = step.product.ingredients
                assert not memberships(items, strict=False).classes & set(cfg.SENSITIVE_STRONG_CLASSES), step.product.name
                assert not set(cfg.SENSITIVE_EXCLUDED_INGREDIENTS) & set(items.tokens)
                assert not fragrance_tokens(items), step.product.name


def test_no_avoided_ingredient_duplicate_or_clash_with_an_active_in_use(routines):
    """Every ranked product (not only the picks) passes the user's own rules."""
    checked = 0
    for p, routine in routines:
        current = current_use(p)
        if current is None:
            continue
        for _, steps in sessions(routine):
            for step in steps:
                for r in step.ranking.ranked:
                    assert current_use_exclusion(current, r.product, CONFLICTS) is None, (r.product.name, current)
                    checked += 1
    assert checked > 0


def test_no_retinoid_or_leave_on_aha_in_the_morning(routines):
    for _, routine in routines:
        for step in kept_in_order(routine.am):
            assert not in_class(step.product.ingredients, "retinoid", strict=False)
            if step.req.category not in cfg.RINSE_OFF_CATEGORIES:
                assert not in_class(step.product.ingredients, "aha", strict=False)


def test_every_left_out_product_has_a_reason(routines):
    for _, routine in routines:
        for item in routine.left_out:
            assert item.reason and item.sessions


def fingerprint(p, routine):
    out = []
    for _, steps in sessions(routine):
        for step in steps:
            out.append((step.req, step.removed, [r.product.id for r in step.ranking.ranked],
                        [a.product.id for a in step.alternatives], explain(step, p, routine.base_set).text))
    return out, routine.warnings, routine.left_out


def test_the_routine_is_deterministic_and_ignores_catalog_order(routines):
    shuffled = CATALOG[:]
    random.Random(7).shuffle(shuffled)
    for p, routine in routines[::7]:
        assert fingerprint(p, build_routine(p, CATALOG, CONFLICTS)) == fingerprint(p, routine)
        assert fingerprint(p, build_routine(p, shuffled, CONFLICTS)) == fingerprint(p, routine)


# --------------------------------------------------------------------------------------
# A recorded snapshot of a few routines on the real catalog
# --------------------------------------------------------------------------------------

SCORES = te.SCORES


def case(skin_type, sensitive=False, tags=None, **scores):
    return SimpleNamespace(skin_type=skin_type, is_sensitive=sensitive, questionnaire_tags=tags,
                           **{s: scores.get(s, 30) for s in SCORES})


SNAPSHOT_CASES = {
    "oily_low": case("oily", **dict.fromkeys(SCORES, 20)),
    "dry_high": case("dry", **dict.fromkeys(SCORES, 75)),
    "combination_wrinkle_45": case("combination", wrinkle_score=45),
    "normal_acne_and_pigmentation": case("normal", acne_score=61, pigmentation_score=61),
    "normal_pores": case("normal", pore_score=80),
    "normal_sensitive_redness": case("normal", True, redness_score=70),
    "normal_sensitive_high": case("normal", True, **dict.fromkeys(SCORES, 75)),
    "oily_sensitive_acne_high": case("oily", True, acne_score=75),
    "dry_wrinkle_high": case("dry", wrinkle_score=75),
    "normal_pigmentation_high": case("normal", pigmentation_score=75),
    "oily_acne_high_avoid_fragrance_salicylic_in_use": case(
        "oily", tags=tc.tags(avoid=["fragrance"], actives_in_use=["salicylic acid"]), acne_score=75),
}


def summarise(p, routine) -> dict:
    def steps(session):
        return [
            {"category": s.req.category, "rule": s.req.source, "keywords": list(s.req.keywords),
             "product": s.product.name, "matched_keyword": s.matched_keyword, "note": s.req.note,
             "caution": s.caution, "why": list(explain(s, p, routine.base_set).text),
             "alternatives": [a.product.name for a in s.alternatives]}
            for s in kept_in_order(session)
        ]

    return {
        "base_set": routine.base_set,
        "am": steps(routine.am),
        "pm": steps(routine.pm),
        "warnings": routine.warnings,
        "left_out": [[lo.product_name, list(lo.sessions), lo.reason] for lo in routine.left_out],
        "unfilled": [[u.session, u.req.category, u.req.source, list(u.req.keywords),
                      "excluded" if u.excluded else "none in catalog", list(u.codes)] for u in routine.unfilled],
    }


def test_the_real_catalog_routines_match_the_recorded_snapshot():
    actual = {name: summarise(p, build_routine(p, CATALOG, CONFLICTS)) for name, p in SNAPSHOT_CASES.items()}
    check_snapshot("routine_real_catalog", actual)
