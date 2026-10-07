"""The 7c-iii old-vs-new record for the real catalog: each product under the frozen
ingredients-1.1.0 vocabulary and under the current one.

Under 1.1.0 every real product has names the vocabulary didn't know, so the engine left
each one out entirely ("unknown ingredients"). The table records what each product is
under the current vocabulary instead; it is a reviewed snapshot
(app/tests/snapshots/catalog_vocabulary_diff.json), so any vocabulary change that alters a
real product shows up here. The vocabulary itself only grew (test_vocabulary.py).
"""

import json

import pytest

from app.services.catalog import load_catalog
from app.services.ingredients import anhydrous_oil, canonical, fragrance_tokens, memberships, mineral_only
from app.services.ingredients import ingredient_config as cfg
from app.services.ingredients.normalise import KNOWN, clean
from app.services.ingredients.tests.test_vocabulary import FROZEN_1_1_0
from app.tests.snapshot import check_snapshot

STRONG = ("retinoid", "benzoyl_peroxide", "aha", "bha")


def vocabulary(synonyms: dict, known: set):
    """canonical() for a given vocabulary: the same three steps as normalise.canonical()."""
    def canonical_with(raw: str) -> str:
        name, brackets = clean(raw)
        token = synonyms.get(name, name)
        if token in known:
            return token
        for alias in brackets:
            alias_token = synonyms.get(alias, alias)
            if alias_token in known:
                return alias_token
        return token
    return canonical_with


OLD_KNOWN = ({t for members in FROZEN_1_1_0["classes"].values() for t in members}
             | set(FROZEN_1_1_0["neutral"]) | set(FROZEN_1_1_0["preservatives"]))
CANONICAL_1_1_0 = vocabulary(FROZEN_1_1_0["synonyms"], OLD_KNOWN)


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


def test_the_replica_matches_canonical_with_the_current_vocabulary(catalog):
    """So the 1.1.0 column can't drift from how canonical() really works."""
    current = vocabulary(cfg.SYNONYMS, KNOWN)
    for product in catalog.products:
        for name in product.ingredient_names:
            assert current(name) == canonical(name), name


def diff_rows(catalog) -> dict:
    rows = {}
    for p in catalog.products:
        old_unknown = sorted({t for t in map(CANONICAL_1_1_0, p.ingredient_names) if t not in OLD_KNOWN})
        found = memberships(p.ingredients, strict=False)
        rows[p.catalog_id] = {
            "1.1.0": f"left out: {len(old_unknown)} unknown names" if old_unknown else "fully known",
            "1.2.0": "fully known" if p.ingredients.fully_known else "unknown names",
            "strong actives": sorted(found.classes & set(STRONG)),
            "fragrance": list(fragrance_tokens(p.ingredients)),
            "mineral_only": mineral_only(p.ingredients),
            "anhydrous_oil": anhydrous_oil(p.ingredients),
            "classes": sorted(found.classes - set(STRONG)),
            "constraints": {c: ok for c, ok in p.constraints},
        }
    return rows


def test_under_1_1_0_every_real_product_was_left_out(catalog):
    rows = diff_rows(catalog)
    assert all(row["1.1.0"].startswith("left out") for row in rows.values())
    assert all(row["1.2.0"] == "fully known" for row in rows.values())


def test_the_real_catalog_diff_is_recorded(catalog):
    check_snapshot("catalog_vocabulary_diff", json.loads(json.dumps(diff_rows(catalog))))
