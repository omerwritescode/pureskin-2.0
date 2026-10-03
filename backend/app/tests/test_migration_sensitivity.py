"""Migration db1f2fceaf09 (is_sensitive + score_sources) up and down, on a throwaway DB."""

import pytest
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.tests.db import downgrade, throwaway_database, upgrade

BEFORE, AFTER = "3641b04c0465", "db1f2fceaf09"

INSERT_OLD = text(
    "INSERT INTO skin_profiles (user_id, acne_score, redness_score, wrinkle_score, "
    "pigmentation_score, pore_score, skin_type) VALUES (:u, 40, 50, 60, 70, 80, :t) RETURNING id"
)


def profiles(engine: Engine) -> dict[int, dict]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT * FROM skin_profiles ORDER BY id")).mappings().all()
    return {row["id"]: dict(row) for row in rows}


def columns(engine: Engine) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns("skin_profiles")}


@pytest.fixture
def old_schema_db():
    """A throwaway DB at the revision before this one, with step 6-era rows in it."""
    with throwaway_database() as engine:
        upgrade(engine, BEFORE)
        with engine.begin() as conn:
            user = conn.execute(
                text("INSERT INTO users (email, hashed_password) VALUES ('m@example.com', 'x') "
                     "RETURNING id")
            ).scalar_one()
            ids = {
                t: conn.execute(INSERT_OLD, {"u": user, "t": t}).scalar_one()
                for t in ("sensitive", "oily", "combination", None)
            }
            conn.execute(
                text("INSERT INTO scan_history (user_id, skin_profile_id) VALUES (:u, :p)"),
                {"u": user, "p": ids["sensitive"]},
            )
        yield engine, user, ids


def test_upgrade_migrates_sensitive_rows_and_leaves_others(old_schema_db):
    engine, _, ids = old_schema_db
    before = profiles(engine)
    upgrade(engine, AFTER)
    after = profiles(engine)

    assert {"is_sensitive", "score_sources"} <= columns(engine)
    sensitive = after[ids["sensitive"]]
    assert (sensitive["skin_type"], sensitive["is_sensitive"]) == ("normal", True)
    for t in ("oily", "combination", None):
        row = after[ids[t]]
        assert (row["skin_type"], row["is_sensitive"], row["score_sources"]) == (t, False, None)
    for row_id, row in after.items():  # scores untouched
        for score in ("acne_score", "redness_score", "wrinkle_score", "pigmentation_score",
                      "pore_score", "created_at"):
            assert row[score] == before[row_id][score]
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM scan_history")).scalar_one() == 1


def test_check_constraint_after_upgrade(old_schema_db):
    engine, user, _ = old_schema_db
    upgrade(engine, AFTER)
    with engine.connect() as conn, pytest.raises(IntegrityError):
        conn.execute(INSERT_OLD, {"u": user, "t": "sensitive"})


def test_downgrade_restores_sensitive_rows(old_schema_db):
    engine, user, ids = old_schema_db
    before = profiles(engine)
    upgrade(engine, AFTER)
    with engine.begin() as conn:  # a post-upgrade row with a real type AND sensitivity
        oily_sensitive = conn.execute(
            text(
                "INSERT INTO skin_profiles (user_id, acne_score, redness_score, wrinkle_score, "
                "pigmentation_score, pore_score, skin_type, is_sensitive, score_sources) VALUES "
                "(:u, 30, 30, 30, 30, 30, 'oily', true, '{\"skin_type\": \"questionnaire\"}') "
                "RETURNING id"
            ),
            {"u": user},
        ).scalar_one()

    downgrade(engine, BEFORE)

    assert not {"is_sensitive", "score_sources"} & columns(engine)
    after = profiles(engine)
    # The migrated row round-trips exactly.
    for row_id in ids.values():
        assert after[row_id] == before[row_id]
    # Lossy by design: the old schema can't hold oily AND sensitive.
    assert after[oily_sensitive]["skin_type"] == "sensitive"
    # The CHECK is gone: the old schema allows 'sensitive' again.
    with engine.begin() as conn:
        conn.execute(INSERT_OLD, {"u": user, "t": "sensitive"})


def test_upgrade_downgrade_upgrade_is_repeatable(old_schema_db):
    engine, _, ids = old_schema_db
    upgrade(engine, AFTER)
    first = profiles(engine)
    downgrade(engine, BEFORE)
    upgrade(engine, AFTER)
    second = profiles(engine)
    for row_id in ids.values():
        assert {k: v for k, v in second[row_id].items() if k != "updated_at"} == {
            k: v for k, v in first[row_id].items() if k != "updated_at"
        }
