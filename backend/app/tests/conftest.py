import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import seed
from app.api import auth, profile, routine, scan_analyze
from app.api.deps import get_db
from app.tests import catalog_fixture
from app.tests.db import throwaway_database, upgrade


@pytest.fixture(scope="session")
def migrated_db():
    """A throwaway database at the latest migration, with the test-only fixture catalog
    (app/tests/catalog_fixture.py: the 24 step 6 placeholders, ids 1..24, which the routine
    snapshots were recorded on) and the real conflict table."""
    with throwaway_database() as engine:
        upgrade(engine)
        Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        with Session() as db:
            catalog_fixture.insert_products(db)
            seed.seed_conflicts(db)
            db.commit()
        yield engine


@pytest.fixture(scope="session")
def api(migrated_db):
    """Auth, scan analysis, profile and routine endpoints wired to the throwaway database."""
    Session = sessionmaker(bind=migrated_db, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    for module in (auth, scan_analyze, profile, routine):
        app.include_router(module.router)
    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


@pytest.fixture
def auth_headers(api):
    """A fresh user (so tests don't see each other's profiles) and their bearer header."""
    response = api.post(
        "/api/auth/register",
        json={
            "email": f"test-{uuid.uuid4().hex[:10]}@example.com",
            "password": "correct-horse-battery",
            "full_name": "Test User",
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
