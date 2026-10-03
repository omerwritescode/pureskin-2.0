"""Step 7c-i (b) migrations, on throwaway databases:

- 047c98cb091a: conflict rows may name a class ("class:<name>"); CHECKs keep class
  references and ingredient names apart.
- 99aa1b05ae54: products.spf, texture, foaming, with controlled-vocabulary CHECKs.

Also: Python's sort and the database's COLLATE "C" order agree on every name the
vocabulary can produce, so normalize_ingredient_pair() always satisfies pair_ordered.
"""

import random

import pytest
from sqlalchemy import Engine, bindparam, inspect, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.exc import IntegrityError
from sqlalchemy.types import Text

from app.core.utils import normalize_ingredient_pair
from app.services.ingredients import CLASS_PREFIX, ingredient_config as icfg
from app.services.ingredients.normalise import KNOWN
from app.tests.db import downgrade, throwaway_database, upgrade

BEFORE, CLASS_NAMES, PRODUCT_FIELDS = "db1f2fceaf09", "047c98cb091a", "99aa1b05ae54"

INSERT_CONFLICT = text(
    "INSERT INTO ingredient_conflicts (ingredient_a, ingredient_b, severity) VALUES (:a, :b, 'low')"
)


def product_columns(engine: Engine) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns("products")}


def check_names(engine: Engine, table: str) -> set[str]:
    return {c["name"] for c in inspect(engine).get_check_constraints(table)}


@pytest.fixture(scope="module")
def db():
    with throwaway_database() as engine:
        upgrade(engine)
        yield engine


def conflict_rows(engine: Engine) -> set[tuple[str, str]]:
    with engine.connect() as conn:
        return {tuple(r) for r in conn.execute(text("SELECT ingredient_a, ingredient_b FROM ingredient_conflicts"))}


def test_upgrade_downgrade_upgrade():
    with throwaway_database() as engine:
        upgrade(engine, BEFORE)
        with engine.begin() as conn:
            conn.execute(INSERT_CONFLICT, {"a": "glycolic acid", "b": "retinol"})
            conn.execute(text(
                "INSERT INTO products (name, brand, category, ingredients) "
                "VALUES ('P', 'B', 'cleanser', ARRAY['water'])"
            ))

        # Up: columns and CHECKs added, existing rows untouched.
        upgrade(engine, PRODUCT_FIELDS)
        assert {"spf", "texture", "foaming"} <= product_columns(engine)
        assert {"ck_ingredient_conflicts_ingredient_a_name", "ck_ingredient_conflicts_ingredient_b_name"} <= (
            check_names(engine, "ingredient_conflicts"))
        assert conflict_rows(engine) == {("glycolic acid", "retinol")}
        with engine.connect() as conn:
            assert tuple(conn.execute(text("SELECT spf, texture, foaming FROM products")).one()) == (None, None, None)
        with engine.begin() as conn:  # what seed.py adds after the upgrade
            conn.execute(INSERT_CONFLICT, {"a": "class:aha", "b": "class:retinoid"})
            conn.execute(text("UPDATE products SET texture = 'gel', foaming = 'foaming', spf = NULL"))

        # Down: class-level rows deleted (the older code can't read them), ingredient-level
        # rows kept; columns and CHECKs dropped.
        downgrade(engine, BEFORE)
        assert not {"spf", "texture", "foaming"} & product_columns(engine)
        assert "ck_ingredient_conflicts_ingredient_a_name" not in check_names(engine, "ingredient_conflicts")
        assert conflict_rows(engine) == {("glycolic acid", "retinol")}

        # Up again: clean, and class rows can be added once more.
        upgrade(engine, PRODUCT_FIELDS)
        assert {"spf", "texture", "foaming"} <= product_columns(engine)
        with engine.begin() as conn:
            conn.execute(INSERT_CONFLICT, {"a": "class:aha", "b": "class:retinoid"})
        assert conflict_rows(engine) == {("glycolic acid", "retinol"), ("class:aha", "class:retinoid")}


# --------------------------------------------------------------------------------------
# Class references vs ingredient names
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b"),
    [("benzoyl peroxide", "class:retinoid"), ("class:aha", "class:bha"), ("ascorbic acid", "niacinamide")],
)
def test_names_the_check_accepts(db, a, b):
    with db.connect() as conn:
        conn.execute(INSERT_CONFLICT, {"a": a, "b": b})
        conn.rollback()


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("benzoyl peroxide", "class:"),
        ("benzoyl peroxide", "class:Retinoid"),
        ("benzoyl peroxide", "class:retinoid "),
        ("benzoyl peroxide", "class:ret-inoid"),
        ("benzoyl peroxide", "foo:bar"),
        ("a:b", "benzoyl peroxide"),
    ],
)
def test_names_the_check_rejects(db, a, b):
    with db.connect() as conn:
        with pytest.raises(IntegrityError, match="_name"):
            conn.execute(INSERT_CONFLICT, {"a": a, "b": b})
        conn.rollback()


# --------------------------------------------------------------------------------------
# Products: format field CHECKs
# --------------------------------------------------------------------------------------

INSERT_PRODUCT = text(
    "INSERT INTO products (name, brand, category, ingredients, spf, texture, foaming) "
    "VALUES ('P', 'B', :category, ARRAY['water'], :spf, :texture, :foaming)"
)


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"category": "cleanser", "spf": None, "texture": "paste", "foaming": None}, "texture"),
        ({"category": "cleanser", "spf": None, "texture": None, "foaming": "very"}, "foaming"),
        ({"category": "serum", "spf": None, "texture": None, "foaming": "foaming"}, "foaming_cleanser_only"),
        ({"category": "sunscreen", "spf": 0, "texture": None, "foaming": None}, "spf_range"),
        ({"category": "sunscreen", "spf": 101, "texture": None, "foaming": None}, "spf_range"),
    ],
)
def test_product_checks_reject(db, values, constraint):
    with db.connect() as conn:
        with pytest.raises(IntegrityError, match=f"ck_products_{constraint}"):
            conn.execute(INSERT_PRODUCT, values)
        conn.rollback()


def test_product_checks_accept(db):
    with db.connect() as conn:
        conn.execute(INSERT_PRODUCT, {"category": "cleanser", "spf": None, "texture": "milk", "foaming": "non_foaming"})
        conn.execute(INSERT_PRODUCT, {"category": "sunscreen", "spf": 50, "texture": "fluid", "foaming": None})
        conn.rollback()


# --------------------------------------------------------------------------------------
# Python sorted() == COLLATE "C" on every name the vocabulary can produce
# --------------------------------------------------------------------------------------

CLASS_REFS = sorted(CLASS_PREFIX + c for c in icfg.CLASSES)
ADVERSARIAL = [
    "1,2-hexanediol", "ci 77891", "caprylic/capric triglyceride", "alpha-isomethyl ionone",
    "a b", "a-b", "a/b", "ab", "a", "b", "z", "0", "9", "class", "classic", "c:",
    "é", "ß", "zinc oxide ", " zinc oxide",
]
CORPUS = sorted(set(KNOWN) | set(CLASS_REFS) | set(ADVERSARIAL))


def test_the_database_is_utf8(db):
    """The equivalence below relies on UTF-8: its byte order is code-point order."""
    with db.connect() as conn:
        assert conn.execute(text("SHOW server_encoding")).scalar_one() == "UTF8"


def test_python_and_collate_c_order_names_identically(db):
    query = text('SELECT x FROM unnest(:xs) AS x ORDER BY x COLLATE "C"').bindparams(
        bindparam("xs", type_=ARRAY(Text))
    )
    with db.connect() as conn:
        assert conn.execute(query, {"xs": CORPUS}).scalars().all() == sorted(CORPUS)


def test_python_and_collate_c_agree_on_every_pair(db):
    query = text(
        'SELECT a, b, a < b COLLATE "C" FROM unnest(:xs) AS a, unnest(:xs) AS b'
    ).bindparams(bindparam("xs", type_=ARRAY(Text)))
    with db.connect() as conn:
        rows = conn.execute(query, {"xs": CORPUS}).all()
    assert len(rows) == len(CORPUS) ** 2
    disagreements = [(a, b) for a, b, less in rows if less != (a < b)]
    assert disagreements == []


def test_normalized_pairs_always_satisfy_pair_ordered(db):
    plain = sorted(KNOWN)
    sample = random.Random(20261003).sample(plain, 25)
    pairs = [(c, p) for c in CLASS_REFS for p in sample] + list(zip(sample, sample[1:]))
    with db.connect() as conn:
        for x, y in pairs:
            a, b = normalize_ingredient_pair(x, y)
            with conn.begin_nested():
                conn.execute(INSERT_CONFLICT, {"a": a, "b": b})
            with pytest.raises(IntegrityError, match="pair_ordered"), conn.begin_nested():
                conn.execute(INSERT_CONFLICT, {"a": b, "b": a})
        conn.rollback()
