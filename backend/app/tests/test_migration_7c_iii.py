"""Step 7c-iii migration 1bb224b28584 (product provenance), on throwaway databases:
up/down/up keeps every product row, and each CHECK accepts and rejects what it should."""

import pytest
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.models.product import PROVENANCE
from app.tests.db import downgrade, throwaway_database, upgrade

BEFORE, PROVENANCE_REV = "440d5393300d", "1bb224b28584"
CHECKS = {"ck_products_market", "ck_products_fetch_status", "ck_products_source_url_https",
          "ck_products_market_matches_fetch_status", "ck_products_provenance_all_or_none"}
SET_PROVENANCE = text(
    "UPDATE products SET source_url = 'https://brand.example/p', market = 'global', "
    "fetch_status = 'ok_global_market', date_checked = DATE '2026-10-06', original_name = 'Brand Product'"
)


def product_columns(engine: Engine) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns("products")}


def check_names(engine: Engine) -> set[str]:
    return {c["name"] for c in inspect(engine).get_check_constraints("products")}


def product_rows(engine: Engine) -> list[tuple]:
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text("SELECT id, name, brand, ingredients FROM products ORDER BY id"))]


def test_upgrade_downgrade_upgrade_keeps_the_rows():
    with throwaway_database() as engine:
        upgrade(engine, BEFORE)
        with engine.begin() as conn:  # a placeholder-era row (no provenance)
            conn.execute(text("INSERT INTO products (name, brand, category, ingredients) "
                              "VALUES ('P', 'B', 'serum', ARRAY['water', 'niacinamide'])"))
        before = product_rows(engine)

        # Up: five nullable columns and the CHECKs; the existing row untouched, all NULL
        upgrade(engine, PROVENANCE_REV)
        assert set(PROVENANCE) <= product_columns(engine)
        assert CHECKS <= check_names(engine)
        assert product_rows(engine) == before
        with engine.begin() as conn:
            assert conn.execute(text("SELECT " + ", ".join(PROVENANCE) + " FROM products")).one() == (None,) * 5
            conn.execute(SET_PROVENANCE)  # what seed.py does for a catalog product

        # Down: CHECKs and columns dropped; every row kept
        downgrade(engine, BEFORE)
        assert not set(PROVENANCE) & product_columns(engine)
        assert not CHECKS & check_names(engine)
        assert product_rows(engine) == before

        # Up again: clean; the row is back with NULL provenance until seed.py fills it
        upgrade(engine, PROVENANCE_REV)
        assert CHECKS <= check_names(engine)
        assert product_rows(engine) == before
        with engine.begin() as conn:
            assert conn.execute(text("SELECT market FROM products")).scalar_one() is None
            conn.execute(SET_PROVENANCE)


@pytest.fixture(scope="module")
def db():
    with throwaway_database() as engine:
        upgrade(engine)
        yield engine


INSERT = text(
    "INSERT INTO products (name, brand, category, ingredients, source_url, market, fetch_status, "
    "date_checked, original_name) VALUES ('P', 'B', 'serum', ARRAY['water'], :source_url, :market, "
    ":fetch_status, CAST(:date_checked AS date), :original_name)"
)
GOOD = {"source_url": "https://brand.example/p", "market": "india", "fetch_status": "ok",
        "date_checked": "2026-10-06", "original_name": "Brand P"}
NONE = dict.fromkeys(GOOD)


@pytest.mark.parametrize("values", [
    GOOD,
    {**GOOD, "market": "global", "fetch_status": "ok_global_market"},
    NONE,  # the tests' fixture catalog, and placeholder rows before seed.py prunes them
])
def test_product_provenance_checks_accept(db, values):
    with db.connect() as conn:
        conn.execute(INSERT, values)
        conn.rollback()


@pytest.mark.parametrize(("values", "constraint"), [
    ({**GOOD, "market": "europe"}, "ck_products_market"),
    ({**GOOD, "fetch_status": "ok_names_only"}, "ck_products_fetch_status"),
    ({**GOOD, "source_url": "http://brand.example/p"}, "ck_products_source_url_https"),
    ({**GOOD, "source_url": "https://brand.example/a b"}, "ck_products_source_url_https"),
    ({**GOOD, "market": "global"}, "ck_products_market_matches_fetch_status"),
    ({**GOOD, "fetch_status": "ok_global_market"}, "ck_products_market_matches_fetch_status"),
    ({**NONE, "source_url": "https://brand.example/p"}, "ck_products_provenance_all_or_none"),
    ({**GOOD, "original_name": None}, "ck_products_provenance_all_or_none"),
])
def test_product_provenance_checks_reject(db, values, constraint):
    with db.connect() as conn:
        with pytest.raises(IntegrityError, match=constraint):
            conn.execute(INSERT, values)
        conn.rollback()
