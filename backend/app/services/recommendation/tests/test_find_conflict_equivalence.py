"""Unit 2a: find_conflict checks each conflict-table row against the two products' keys
instead of every pair of keys. Its result must be IDENTICAL to the old implementation's,
kept below verbatim as the reference: the same Conflict object (so the same row, severity
and reason text), including which one is returned when several match (the most severe;
among equals, the first a walk through a's keys, then b's, meets).

Compared on every ordered pair of the 37 real products and of the 24 fixture products,
under the real conflict table and under random tables (fixed seed) built to produce many
ties, and on random sessions mixing both catalogs.
"""

import itertools
import random

import seed
from app.core.utils import normalize_ingredient_pair
from app.services.catalog import load_catalog, product_records
from app.services.ingredients import CLASS_PREFIX, memberships
from app.services.recommendation import routine_config as cfg
from app.services.recommendation.engine import Conflict, conflict_table, find_conflict
# SEED_PRODUCTS exists both before and after the fixture move, so this test works in either tree.
from app.services.recommendation.tests.test_engine import SEED_PRODUCTS

REAL = product_records(load_catalog())
FIXTURE = SEED_PRODUCTS
TABLE = conflict_table(seed.CONFLICTS)
SEVERITIES = ("high", "medium", "low")


# --------------------------------------------------------------------------------------
# The reference: find_conflict and conflict_keys as they were before unit 2a (commit
# 72f3ca1), verbatim apart from the names; most_severe inlined.
# --------------------------------------------------------------------------------------


def reference_conflict_keys(product) -> list[str]:
    classes = memberships(product.ingredients, strict=False).classes
    return [*product.ingredients.tokens, *(CLASS_PREFIX + c for c in sorted(classes))]


def reference_find_conflict(a, b, conflicts):
    found = []
    for key_a in reference_conflict_keys(a):
        for key_b in reference_conflict_keys(b):
            if key_a == key_b:  # the same ingredient (or class) in both: not a conflict
                continue
            conflict = conflicts.get(normalize_ingredient_pair(key_a, key_b))
            if conflict is not None:
                found.append(conflict)
    return min(found, key=lambda c: cfg.SEVERITY_ORDER.index(c.severity), default=None)


# --------------------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------------------


def matches(a, b, conflicts) -> int:
    """How many (key_a, key_b) pairs the old walk finds (2+ means a tie order matters)."""
    keys_b = reference_conflict_keys(b)
    return sum(1 for key_a in reference_conflict_keys(a) for key_b in keys_b
               if key_a != key_b and normalize_ingredient_pair(key_a, key_b) in conflicts)


def assert_same(pairs, conflicts) -> dict:
    stats = {"pairs": 0, "found": 0, "several": 0, "tie": 0}
    for a, b in pairs:
        old = reference_find_conflict(a, b, conflicts)
        new = find_conflict(a, b, conflicts)
        assert new is old, (a.name, b.name, old, new)  # the very same row object
        if old is not None:
            assert (new.severity, new.reason, new.pair) == (old.severity, old.reason, old.pair)
            stats["found"] += 1
            n = matches(a, b, conflicts)
            stats["several"] += n > 1
            keys_a, keys_b = reference_conflict_keys(a), reference_conflict_keys(b)
            severities = [conflicts[normalize_ingredient_pair(x, y)].severity for x in keys_a for y in keys_b
                          if x != y and normalize_ingredient_pair(x, y) in conflicts]
            stats["tie"] += severities.count(old.severity) > 1  # equally severe rows: the order decides
        stats["pairs"] += 1
    return stats


def random_table(rng: random.Random, products) -> dict:
    """Random rows over keys these products really have (tokens and classes), with random
    severities and reasons, so many pairs match several rows of the same severity."""
    keys = sorted({k for p in products for k in reference_conflict_keys(p)})
    rows = []
    for _ in range(rng.randint(40, 120)):
        a, b = rng.sample(keys, 2)
        rows.append((a, b, rng.choice(SEVERITIES), f"reason {len(rows)} for {a} + {b}"))
    rows += [(a, b, rng.choice(SEVERITIES), reason) for a, b, _, reason in seed.CONFLICTS if rng.random() < 0.7]
    return conflict_table(rows)


# --------------------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------------------


def test_conflict_keys_are_already_normalised():
    """normalize_ingredient_pair() trims and lowercases; on these keys that changes nothing,
    which is what lets the new code match keys against the table's pairs directly."""
    for product in [*REAL, *FIXTURE]:
        for key in reference_conflict_keys(product):
            assert key == key.strip().lower(), (product.name, key)


def test_every_ordered_pair_of_real_products_under_the_real_table():
    stats = assert_same(itertools.product(REAL, repeat=2), TABLE)
    assert stats["pairs"] == 37 * 37 and stats["found"] > 0


def test_every_ordered_pair_of_fixture_products_under_the_real_table():
    stats = assert_same(itertools.product(FIXTURE, repeat=2), TABLE)
    assert stats["pairs"] == 24 * 24 and stats["found"] > 0


def test_every_ordered_pair_under_random_tables_with_ties():
    rng = random.Random(20261007)
    totals = {"pairs": 0, "found": 0, "several": 0, "tie": 0}
    for catalog in (REAL, FIXTURE):
        for _ in range(12):
            stats = assert_same(itertools.product(catalog, repeat=2), random_table(rng, catalog))
            totals = {k: totals[k] + stats[k] for k in totals}
    assert totals["tie"] > 1000  # the tie order is exercised, not only the severity order


def test_random_sessions_and_subsets_mixing_both_catalogs():
    rng = random.Random(7)
    both = [*REAL, *FIXTURE]
    for _ in range(300):
        session = rng.sample(both, rng.randint(2, 8))
        conflicts = TABLE if rng.random() < 0.5 else random_table(rng, session)
        assert_same(itertools.permutations(session, 2), conflicts)


def test_no_conflict_rows_and_unrelated_rows():
    a, b = REAL[0], REAL[1]
    assert find_conflict(a, b, {}) is None is reference_find_conflict(a, b, {})
    unrelated = {("zz unknown a", "zz unknown b"): Conflict("high", "never", ("zz unknown a", "zz unknown b"))}
    assert find_conflict(a, b, unrelated) is None
