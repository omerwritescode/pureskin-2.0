"""Throwaway PostgreSQL databases for tests.

Each one is created in the local Docker instance under a random name, migrated with
Alembic, and dropped afterwards, so tests never touch the dev database named in .env.
Tests that need one are skipped when PostgreSQL isn't reachable.
"""

import contextlib
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from app.core.config import settings

BACKEND_DIR = Path(__file__).resolve().parents[2]


def alembic_config() -> Config:
    # Built without alembic.ini on purpose: env.py then skips logging.config.fileConfig,
    # which would disable the loggers pytest (caplog) relies on.
    config = Config()
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return config


def upgrade(engine: Engine, revision: str = "head") -> None:
    config = alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, revision)


def downgrade(engine: Engine, revision: str) -> None:
    config = alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, revision)


@contextlib.contextmanager
def throwaway_database() -> Iterator[Engine]:
    """An empty database (no tables yet) that is dropped on exit."""
    url = make_url(settings.DATABASE_URL)
    name = f"pureskin_test_{uuid.uuid4().hex[:12]}"
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
    except OperationalError as exc:
        admin.dispose()
        pytest.skip(f"PostgreSQL not reachable (start it with `docker compose up -d`): {exc}")

    engine = create_engine(url.set(database=name))
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()
