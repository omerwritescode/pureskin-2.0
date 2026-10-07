"""seed.py: conflict names and class rows, the strong-active derivation, and pruning
(step 7c-i b); products seeded from backend/catalog/products.json through the catalog
loader, the placeholders pruned, and the test-only fixture kept out of the seed path
(step 7c-iii)."""

import json
import subprocess
import sys
from datetime import date

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

import seed
from app.models import IngredientConflict, Product
from app.models.product import FETCH_STATUSES, MARKETS, PROVENANCE
from app.services.catalog import CatalogError, catalog_config as ccfg, check_rows, load_catalog
from app.services.catalog.loader import CATALOG_FILE, verbatim_sha256
from app.services.ingredients import CLASS_PREFIX, check_conflict_name, ingredient_config as icfg
from app.services.ingredients.normalise import TOKEN_CLASSES
from app.services.recommendation import routine_config as rcfg
from app.tests import catalog_fixture
from app.tests.db import BACKEND_DIR, throwaway_database, upgrade


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
# Products: the catalog, through the loader; the placeholders pruned
# --------------------------------------------------------------------------------------


def products(db) -> list[Product]:
    return list(db.scalars(select(Product).order_by(Product.id)))


def test_seeding_makes_products_exactly_the_catalog_and_prunes_the_placeholders(capsys):
    catalog = load_catalog()
    with throwaway_database() as engine:
        upgrade(engine)
        Session = sessionmaker(bind=engine)
        with Session() as db:  # a dev database as it was before 7c-iii: the placeholders
            catalog_fixture.insert_products(db)
            db.commit()
            assert seed.seed_products(db, catalog) == (37, 0, 24)
            db.commit()
            rows = products(db)
        printed = capsys.readouterr().out
        assert printed.count("Inserted product: ") == 37 and printed.count("Pruned product: ") == 24
        assert "Pruned product: Dermaveil - Clear Balance Foaming Cleanser (id 1)" in printed
        assert "Inserted product: B01 Minimalist - Aquaporin Booster 05% Cleanser (cleanser, india, id 25)" in printed

        # Exactly the catalog, in file order, every row with its provenance
        assert [(r.brand, r.name) for r in rows] == [(p.brand, p.name) for p in catalog.products]
        by_name = {(r.brand, r.name): r for r in rows}
        for p in catalog.products:
            row = by_name[(p.brand, p.name)]
            assert row.ingredients == list(p.ingredient_names)
            assert (row.category, row.texture, row.foaming, row.spf) == (p.category, p.texture, p.foaming, p.spf)
            assert (row.source_url, row.market, row.fetch_status, row.original_name) == (
                p.source_url, p.market, p.fetch_status, p.original_name)
            assert row.date_checked == date.fromisoformat(p.date_checked)
            assert row.description is None and row.image_url is None
        b15 = by_name[("The Derma Co.", "Ultra Light Zinc Mineral Sunscreen")]
        assert (b15.spf, b15.market) == (50, "india")
        assert by_name[("The Derma Co.", "Creamy Cleanser")].foaming == "non_foaming"
        assert sum(r.market == "global" for r in rows) == 13

        # Idempotent; a changed row is updated (and printed with the fields that changed)
        with Session() as db:
            assert seed.seed_products(db, catalog) == (0, 0, 0)
            db.execute(text("UPDATE products SET texture = NULL WHERE name = 'Creamy Cleanser'"))
            db.expire_all()  # the session read the rows above; read them again
            assert seed.seed_products(db, catalog) == (0, 1, 0)
            db.commit()
        assert "Updated product: B04 The Derma Co. - Creamy Cleanser (texture)" in capsys.readouterr().out


def test_a_catalog_problem_stops_the_seed_before_anything_is_written(monkeypatch, capsys):
    def refused():
        raise CatalogError(["B22: source_url 'http://x' is not an https URL"])

    def no_database():
        raise AssertionError("the database was opened")

    monkeypatch.setattr(seed, "load_catalog", refused)
    monkeypatch.setattr(seed, "SessionLocal", no_database)
    with pytest.raises(SystemExit) as stop:
        seed.main()
    assert stop.value.code == 1
    assert "- B22: source_url 'http://x' is not an https URL" in capsys.readouterr().out


def test_the_seed_path_never_imports_the_fixture():
    """Importing seed.py and loading the catalog (everything the seed does but the database
    writes) loads no module from app.tests, in a fresh interpreter."""
    code = ("import sys, seed; seed.load_catalog(); "
            "print(sorted(m for m in sys.modules if m == 'app.tests' or m.startswith('app.tests.')))")
    out = subprocess.run([sys.executable, "-c", code], cwd=BACKEND_DIR, capture_output=True, text=True,
                         check=True).stdout
    assert out.strip() == "[]"


def fixture_row(index, name, brand, category, description, ingredients) -> dict:
    """A catalog row made from everything the fixture knows about a product. It has no
    provenance: no source page, market, fetch status, date or staging name."""
    text_ = ", ".join(ingredients)
    fmt = catalog_fixture.PLACEHOLDER_FORMAT.get(name, {})
    return {
        "catalog_id": f"F{index:02d}", "sheet_row": 9000 + index, "slot": "",
        "name": name, "brand": brand, "original_name": None, "category": category,
        "texture": fmt.get("texture"), "foaming": fmt.get("foaming"), "spf": fmt.get("spf"),
        "spf_verbatim": f"SPF {fmt['spf']}" if fmt.get("spf") else "", "market": None, "fetch_status": None,
        "list_kind": None, "copied_from": None, "source_url": None, "retailer_url": None, "date_checked": None,
        "ingredients_verbatim": text_, "verbatim_sha256": verbatim_sha256(text_), "cleaning": {},
        "expected_constraints": [], "preferred": [], "known_mismatches": {}, "notes": description,
        "review_notes": [],
    }


@pytest.mark.parametrize("index", range(len(catalog_fixture.PRODUCTS)),
                         ids=[p[0] for p in catalog_fixture.PRODUCTS])
def test_no_fixture_product_can_pass_the_loader(index):
    loaded, problems = check_rows([fixture_row(index, *catalog_fixture.PRODUCTS[index])])
    assert loaded == []
    for expected in ("is not an https URL", "can't be seeded", "is not a YYYY-MM-DD date",
                     "only a full ingredient list"):
        assert any(expected in p for p in problems), (expected, problems)


def test_no_fixture_product_or_brand_is_in_the_catalog():
    data = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    names = {row["name"] for row in data["products"]} | {row["original_name"] for row in data["products"]}
    brands = {row["brand"] for row in data["products"]}
    assert not names & {p[0] for p in catalog_fixture.PRODUCTS}
    assert not brands & {p[1] for p in catalog_fixture.PRODUCTS}


def test_the_database_and_the_loader_share_the_provenance_vocabularies():
    assert MARKETS == ccfg.MARKETS
    assert FETCH_STATUSES == tuple(ccfg.SEEDABLE_FETCH_STATUS)
    assert set(PROVENANCE) <= set(ccfg.ROW_FIELDS)
    assert rcfg.MIN_SUNSCREEN_SPF == ccfg.MIN_SUNSCREEN_SPF


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
