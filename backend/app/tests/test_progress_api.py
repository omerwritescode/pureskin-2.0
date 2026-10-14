"""Step 8: GET /api/progress, the signed-in user's saved scans oldest first, on a throwaway
database."""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app import main
from app.api import auth, profile, progress
from app.api.deps import get_db

SCORES = ("acne_score", "redness_score", "wrinkle_score", "pigmentation_score", "pore_score")


@pytest.fixture(scope="module")
def client(migrated_db):
    Session = sessionmaker(bind=migrated_db, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    for module in (auth, profile, progress):
        app.include_router(module.router)
    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def sign_up(client, engine) -> tuple[int, dict]:
    email = f"progress-{uuid.uuid4().hex[:10]}@example.com"
    response = client.post("/api/auth/register",
                           json={"email": email, "password": "correct-horse-battery", "full_name": "Progress Probe"})
    assert response.status_code == 201, response.text
    with engine.connect() as conn:
        user_id = conn.execute(text("SELECT id FROM users WHERE email = :e"), {"e": email}).scalar_one()
    return user_id, {"Authorization": f"Bearer {response.json()['access_token']}"}


def scan(client, headers, score, **body):
    response = client.post("/api/profile", headers=headers,
                           json={**dict.fromkeys(SCORES, score), "skin_type": "normal", **body})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_progress_needs_a_token(client):
    assert client.get("/api/progress").status_code == 401


def test_no_scans_is_an_empty_list(client, migrated_db):
    _, headers = sign_up(client, migrated_db)
    assert client.get("/api/progress", headers=headers).json() == {"scans": []}


def test_scans_come_oldest_first_with_their_history_ids(client, migrated_db):
    user_id, headers = sign_up(client, migrated_db)
    first, second = scan(client, headers, 30), scan(client, headers, 70, is_sensitive=True)
    with migrated_db.connect() as conn:
        history = dict(conn.execute(text("SELECT skin_profile_id, id FROM scan_history WHERE user_id = :u"),
                                    {"u": user_id}).all())
    scans = client.get("/api/progress", headers=headers).json()["scans"]
    assert [s["id"] for s in scans] == [first, second]
    assert [s["scan_id"] for s in scans] == [history[first], history[second]]
    assert [s["acne_score"] for s in scans] == [30, 70] and [s["is_sensitive"] for s in scans] == [False, True]
    assert set(scans[0]) == {"id", "scan_id", "created_at", *SCORES, "skin_type", "is_sensitive", "score_sources"}
    assert scans[0]["score_sources"] is None  # saved without sources: a JSON null, read as null


def test_scores_are_whole_numbers_as_on_the_profile_page(client, migrated_db):
    user_id, headers = sign_up(client, migrated_db)
    with migrated_db.begin() as conn:
        conn.execute(text("INSERT INTO skin_profiles (user_id, acne_score, redness_score, wrinkle_score, "
                          "pigmentation_score, pore_score) VALUES (:u, 42.6, 30, 30, 30, 30)"), {"u": user_id})
    assert client.get("/api/progress", headers=headers).json()["scans"][0]["acne_score"] == 43


def test_a_profile_without_a_history_row_still_shows_and_order_is_by_date(client, migrated_db):
    user_id, headers = sign_up(client, migrated_db)
    newer = scan(client, headers, 50)
    with migrated_db.begin() as conn:  # an older profile with no scan_history row (the app never makes one)
        older = conn.execute(text(
            "INSERT INTO skin_profiles (user_id, acne_score, redness_score, wrinkle_score, pigmentation_score, "
            "pore_score, created_at) VALUES (:u, 20, 20, 20, 20, 20, now() - interval '30 days') RETURNING id"),
            {"u": user_id}).scalar_one()
    scans = client.get("/api/progress", headers=headers).json()["scans"]
    assert [(s["id"], s["scan_id"] is None) for s in scans] == [(older, True), (newer, False)]


def test_other_users_scans_never_appear(client, migrated_db):
    _, alice = sign_up(client, migrated_db)
    _, bob = sign_up(client, migrated_db)
    alice_scan = scan(client, alice, 30)
    bob_scans = {scan(client, bob, 60), scan(client, bob, 65)}
    assert [s["id"] for s in client.get("/api/progress", headers=alice).json()["scans"]] == [alice_scan]
    assert {s["id"] for s in client.get("/api/progress", headers=bob).json()["scans"]} == bob_scans


def test_the_app_serves_progress():
    assert "get" in main.app.openapi()["paths"]["/api/progress"]
