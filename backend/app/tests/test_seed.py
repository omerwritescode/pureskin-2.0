"""seed.py: conflict names and class rows, the strong-active derivation, format fields,
the sunscreen SPF rule, and pruning (step 7c-i b)."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

import seed
from app.models import IngredientConflict, Product
from app.models.product import FOAMING, TEXTURES
from app.services.ingredients import CLASS_PREFIX, check_conflict_name, ingredient_config as icfg
from app.services.ingredients.normalise import TOKEN_CLASSES
from app.services.recommendation import routine_config as rcfg
from app.tests.db import throwaway_database, upgrade

PRODUCT_NAMES = {p[0] for p in seed.PRODUCTS}
CATEGORIES = {p[0]: p[2] for p in seed.PRODUCTS}


# --------------------------------------------------------------------------------------
# Conflict rows
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["class:retinoid", "class:aha", "benzoyl peroxide", "ascorbic acid"])
def test_valid_conflict_names(name):
    check_conflict_name(name)


@pytest.mark.parametrize(
    "name",
    ["class:retinoids", "class:", "class:Retinoid", "Retinol", "retinol ", "vitamin c", "mystery acid", "a:b"],
)
def test_invalid_conflict_names(name):
    with pytest.raises(ValueError):
        check_conflict_name(name)


def test_every_seeded_conflict_name_is_valid():
    for a, b, severity, _ in seed.CONFLICTS:
        check_conflict_name(a)
        check_conflict_name(b)
        assert severity in ("low", "medium", "high")


def _classes(name: str) -> set[str]:
    return {name.removeprefix(CLASS_PREFIX)} if name.startswith(CLASS_PREFIX) else set(TOKEN_CLASSES.get(name, ()))


def test_no_ingredient_row_is_covered_by_a_class_row():
    rows = {frozenset((a, b)) for a, b, _, _ in seed.CONFLICTS}
    for a, b, _, _ in seed.CONFLICTS:
        for name, other in ((a, b), (b, a)):
            if name.startswith(CLASS_PREFIX):
                continue
            for cls in TOKEN_CLASSES.get(name, ()):
                assert frozenset((CLASS_PREFIX + cls, other)) not in rows, (a, b)


def test_strong_actives_are_exactly_the_classes_in_high_severity_rows():
    high = {c for a, b, severity, _ in seed.CONFLICTS if severity == "high" for c in _classes(a) | _classes(b)}
    assert set(rcfg.SENSITIVE_STRONG_CLASSES) == high


def test_ascorbic_acid_rows_stay_ingredient_level():
    named = {n for a, b, _, _ in seed.CONFLICTS for n in (a, b)}
    assert "ascorbic acid" in named and "class:vitamin_c" not in named


# --------------------------------------------------------------------------------------
# Products: format fields and the sunscreen SPF rule
# --------------------------------------------------------------------------------------


def test_placeholder_format_fields_use_the_vocabulary():
    assert set(seed.PLACEHOLDER_FORMAT) <= PRODUCT_NAMES
    for name, fields in seed.PLACEHOLDER_FORMAT.items():
        assert set(fields) <= {"texture", "foaming", "spf"}
        assert fields.get("texture") in (None, *TEXTURES)
        assert fields.get("foaming") in (None, *FOAMING)
        if "foaming" in fields:
            assert CATEGORIES[name] == "cleanser"


def test_every_seeded_sunscreen_has_spf_30_or_more():
    for name, _brand, category, description, ingredients in seed.PRODUCTS:
        values = seed.product_values(name, category, description, ingredients)
        if category == "sunscreen":
            assert values["spf"] >= rcfg.MIN_SUNSCREEN_SPF


@pytest.mark.parametrize("spf", [None, 15, 29])
def test_a_sunscreen_without_spf_30_is_refused(monkeypatch, spf):
    fmt = {} if spf is None else {"spf": spf}
    monkeypatch.setitem(seed.PLACEHOLDER_FORMAT, "Test Sunscreen", fmt)
    with pytest.raises(ValueError, match="SPF"):
        seed.product_values("Test Sunscreen", "sunscreen", "", ["Zinc Oxide"])


def test_seeded_rows_carry_the_format_fields(migrated_db):
    Session = sessionmaker(bind=migrated_db)
    with Session() as db:
        rows = {p.name: p for p in db.scalars(select(Product))}
    assert (rows["Invisible Fluid SPF 50"].spf, rows["Invisible Fluid SPF 50"].texture) == (50, "fluid")
    assert rows["Hydra Cream Cleanser"].foaming == "non_foaming"
    assert rows["Peptide Firming Moisturiser"].texture is None


# --------------------------------------------------------------------------------------
# seed_conflicts makes the table exactly CONFLICTS, printing every pruned row
# --------------------------------------------------------------------------------------


def test_seed_conflicts_prunes_and_prints_old_rows(capsys):
    with throwaway_database() as engine:
        upgrade(engine)
        with engine.begin() as conn:  # a step 6-era ingredient-level row
            conn.execute(text(
                "INSERT INTO ingredient_conflicts (ingredient_a, ingredient_b, severity, reason) "
                "VALUES ('glycolic acid', 'retinol', 'high', 'old')"
            ))
        Session = sessionmaker(bind=engine)
        with Session() as db:
            inserted, updated, pruned = seed.seed_conflicts(db)
            db.commit()
            stored = {(c.ingredient_a, c.ingredient_b) for c in db.scalars(select(IngredientConflict))}
        assert (inserted, updated, pruned) == (len(seed.CONFLICTS), 0, 1)
        printed = capsys.readouterr().out
        assert "Pruned conflict: glycolic acid + retinol (high)" in printed
        assert "Inserted conflict: class:aha + class:retinoid (high)" in printed
        assert ("glycolic acid", "retinol") not in stored
        assert ("class:aha", "class:retinoid") in stored
        assert len(stored) == len(seed.CONFLICTS)


def test_ingredient_vocabulary_has_no_class_prefix():
    assert icfg.CLASS_PREFIX == "class:"
