"""Step 8: GET /api/account, the data export and account deletion, on a throwaway database.

- The export holds the caller's rows only, never the password hash, and every column of
  every table that holds a user's data is either exported or deliberately left out.
- Deleting needs the password (a 403 otherwise, never a 401), removes the user's rows in
  every such table (found from the database's own foreign keys) and nobody else's, and the
  deleted user's token then gets a 401 everywhere.
"""

import json
import logging
import uuid
from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app import main
from app.api import account, auth, profile
from app.api.deps import get_db
from app.services.questionnaire import questionnaire_config as qcfg
from app.services.skin_profile import merge_score
from app.services.skin_profile.skin_profile_config import MERGE_CONFIG_VERSION

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
    for module in (auth, profile, account):
        app.include_router(module.router)
    app.add_exception_handler(RequestValidationError, main.validation_error_handler)  # no echo
    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


@dataclass
class Person:
    id: int
    email: str
    password: str
    full_name: str
    headers: dict


def sign_up(client, engine, full_name="Account Probe") -> Person:
    email = f"acct-{uuid.uuid4().hex[:10]}@example.com"
    password = f"pw-{uuid.uuid4().hex[:16]}"
    response = client.post("/api/auth/register", json={"email": email, "password": password, "full_name": full_name})
    assert response.status_code == 201, response.text
    with engine.connect() as conn:
        user_id = conn.execute(text("SELECT id FROM users WHERE email = :e"), {"e": email}).scalar_one()
    return Person(user_id, email, password, full_name, {"Authorization": f"Bearer {response.json()['access_token']}"})


def merged_scan() -> dict:
    """A POST /api/profile body whose scores reproduce from its score_sources (the real merge)."""
    body, entries = {}, {}
    for name, (image, questionnaire) in zip(SCORES, [(20, 65), (40, None), (30, 50), (55, 45), (35, None)]):
        body[name], entries[name] = merge_score(name, image, questionnaire)
    body["score_sources"] = {
        "version": {"image_model": "image-analysis-1.0.0+heuristic-1+skin-type-none",
                    "questionnaire_config": qcfg.CONFIG_VERSION, "merge_config": MERGE_CONFIG_VERSION},
        "skin_type": "questionnaire", "is_sensitive": "questionnaire", "scores": entries,
    }
    return body


TAGS = {"version": qcfg.CONFIG_VERSION, "actives_in_use": ["prescription_retinoid"],
        "products_in_use": ["retinoid"], "avoid": ["fragrance"], "stated_concern": "acne"}


def give_everything(client, engine, person: Person) -> None:
    """Two scans through the API (one with sources and tags, one without either, so its
    score_sources is a JSON null) and a subscription row (the app never writes one)."""
    first = client.post("/api/profile", headers=person.headers,
                        json={**merged_scan(), "skin_type": "oily", "is_sensitive": True, "questionnaire_tags": TAGS})
    assert first.status_code == 201 and first.json()["questionnaire_tags_dropped"] is False, first.text
    second = client.post("/api/profile", headers=person.headers,
                         json={**dict.fromkeys(SCORES, 42), "skin_type": "normal"})
    assert second.status_code == 201, second.text
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO subscriptions (user_id, plan, status) VALUES (:u, 'free', 'active')"),
                     {"u": person.id})


def user_tables(engine) -> dict[str, str]:
    """{table: on-delete action} for every table whose rows hang off a user, directly or
    through another such table, read from the database's own foreign keys."""
    with engine.connect() as conn:
        fks = conn.execute(text("SELECT conrelid::regclass::text, confrelid::regclass::text, confdeltype "
                                "FROM pg_constraint WHERE contype = 'f'")).all()
    reached, actions = {"users"}, {}
    while True:
        found = {(child, parent, action) for child, parent, action in fks if parent in reached}
        new = {child for child, _, _ in found} - reached
        for child, parent, action in found:
            actions.setdefault(child, set()).add(action)
        if not new:
            return {table: "".join(sorted(acts)) for table, acts in actions.items()}
        reached |= new


def row_counts(engine, user_id: int) -> dict[str, int]:
    with engine.connect() as conn:
        counts = {"users": conn.execute(text("SELECT count(*) FROM users WHERE id = :u"), {"u": user_id}).scalar_one()}
        for table in user_tables(engine):
            counts[table] = conn.execute(text(f"SELECT count(*) FROM {table} WHERE user_id = :u"),
                                         {"u": user_id}).scalar_one()
    return counts


def delete_account(client, person: Person, body=None, headers=None):
    body = {"password": person.password} if body is None else body
    return client.request("DELETE", "/api/account", json=body,
                          headers=person.headers if headers is None else headers)


# --------------------------------------------------------------------------------------
# GET /api/account
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(("method", "path"), [("GET", "/api/account"), ("GET", "/api/account/export"),
                                               ("DELETE", "/api/account")])
def test_every_account_endpoint_needs_a_token(client, method, path):
    assert client.request(method, path).status_code == 401
    assert client.request(method, path, headers={"Authorization": "Bearer not-a-token"}).status_code == 401


def test_account_shows_email_name_and_date_and_never_the_hash(client, migrated_db):
    person = sign_up(client, migrated_db)
    body = client.get("/api/account", headers=person.headers).json()
    assert set(body) == {"email", "full_name", "created_at"}
    assert (body["email"], body["full_name"]) == (person.email, person.full_name)
    assert "$2b$" not in json.dumps(body)


# --------------------------------------------------------------------------------------
# GET /api/account/export
# --------------------------------------------------------------------------------------


def test_export_has_the_documented_shape(client, migrated_db):
    person = sign_up(client, migrated_db)
    give_everything(client, migrated_db, person)
    response = client.get("/api/account/export", headers=person.headers)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"].startswith('attachment; filename="pureskin-data-')
    export = response.json()
    assert list(export) == ["format", "exported_at", "account", "skin_profiles", "scan_history", "subscriptions",
                            "about_this_export"]
    assert export["format"] == account.EXPORT_FORMAT
    assert list(export["account"]) == list(account.EXPORTED_COLUMNS["users"])
    assert [export["account"][k] for k in ("id", "email", "full_name")] == [person.id, person.email, person.full_name]
    assert [len(export[t]) for t in ("skin_profiles", "scan_history", "subscriptions")] == [2, 2, 1]
    first, second = export["skin_profiles"]
    assert first["questionnaire_tags"] == TAGS and first["score_sources"]["version"]["merge_config"] == MERGE_CONFIG_VERSION
    assert (first["skin_type"], first["is_sensitive"], first["raw_image_path"]) == ("oily", True, None)
    assert second["score_sources"] is None and second["questionnaire_tags"] is None
    assert {h["skin_profile_id"] for h in export["scan_history"]} == {first["id"], second["id"]}
    assert export["about_this_export"] == account.EXPORT_STATEMENTS


def test_export_contains_only_the_callers_rows(client, migrated_db):
    alice, bob = sign_up(client, migrated_db, "Alice Exportcaller"), sign_up(client, migrated_db, "Bob Neverleaks")
    give_everything(client, migrated_db, alice)
    give_everything(client, migrated_db, bob)
    with migrated_db.connect() as conn:
        bob_profiles = conn.execute(text("SELECT id FROM skin_profiles WHERE user_id = :u"), {"u": bob.id}).scalars().all()
    response = client.get("/api/account/export", headers=alice.headers)
    export = response.json()
    for table in ("skin_profiles", "scan_history", "subscriptions"):
        assert export[table] and {row["user_id"] for row in export[table]} == {alice.id}, table
    assert not {row["id"] for row in export["skin_profiles"]} & set(bob_profiles)
    assert bob.email not in response.text and "Bob Neverleaks" not in response.text


def test_export_never_contains_the_password_hash(client, migrated_db):
    person = sign_up(client, migrated_db)
    with migrated_db.connect() as conn:
        stored_hash = conn.execute(text("SELECT hashed_password FROM users WHERE id = :u"), {"u": person.id}).scalar_one()
    response = client.get("/api/account/export", headers=person.headers)
    assert stored_hash not in response.text and "$2b$" not in response.text
    assert "hashed_password" not in response.text and person.password not in response.text


def test_every_column_is_exported_or_deliberately_left_out(migrated_db):
    """A column added to any table that holds a user's data fails here until it is listed in
    account.EXPORTED_COLUMNS or account.NOT_EXPORTED."""
    tables = {"users", *user_tables(migrated_db)}
    assert tables == set(account.EXPORTED_COLUMNS)
    with migrated_db.connect() as conn:
        for table in tables:
            columns = set(conn.execute(text("SELECT column_name FROM information_schema.columns "
                                            "WHERE table_schema = 'public' AND table_name = :t"), {"t": table}).scalars())
            exported, left_out = set(account.EXPORTED_COLUMNS[table]), set(account.NOT_EXPORTED.get(table, ()))
            assert not exported & left_out, table
            assert columns == exported | left_out, (table, columns ^ (exported | left_out))
    assert account.NOT_EXPORTED == {"users": ("hashed_password",)}


def test_every_table_holding_user_rows_is_exported_and_deleted_with_the_user(migrated_db):
    tables = user_tables(migrated_db)
    assert set(tables) == {"skin_profiles", "scan_history", "subscriptions"}
    assert tables == dict.fromkeys(tables, "c"), tables  # every foreign key: ON DELETE CASCADE


def test_null_score_sources_and_tags_export_as_null(client, migrated_db):
    """score_sources has no none_as_null: a profile saved without sources holds a JSON null,
    and older rows may hold SQL NULL. Both, and a NULL skin type, come out as null."""
    person = sign_up(client, migrated_db)
    with migrated_db.begin() as conn:
        for sources in ("NULL", "'null'::jsonb"):
            conn.execute(text(
                "INSERT INTO skin_profiles (user_id, acne_score, redness_score, wrinkle_score, pigmentation_score, "
                f"pore_score, skin_type, score_sources) VALUES (:u, 42.4, 30, 30, 30, 30, NULL, {sources})"),
                {"u": person.id})
        kinds = conn.execute(text("SELECT score_sources IS NULL FROM skin_profiles WHERE user_id = :u ORDER BY id"),
                             {"u": person.id}).scalars().all()
    assert kinds == [True, False]  # one SQL NULL, one JSON null, as stored
    response = client.get("/api/account/export", headers=person.headers)
    assert response.status_code == 200
    for row in response.json()["skin_profiles"]:
        assert (row["score_sources"], row["questionnaire_tags"], row["skin_type"]) == (None, None, None)
        assert row["acne_score"] == 42.4  # as stored: the export doesn't round, unlike GET /api/profile


# --------------------------------------------------------------------------------------
# DELETE /api/account
# --------------------------------------------------------------------------------------


def test_delete_with_a_wrong_password_is_403_and_deletes_nothing(client, migrated_db):
    person = sign_up(client, migrated_db)
    give_everything(client, migrated_db, person)
    before = row_counts(migrated_db, person.id)
    wrong = "wrong-" + person.password
    response = delete_account(client, person, {"password": wrong})
    assert response.status_code == 403  # never 401: the pages log the user out on any 401
    assert response.json() == {"detail": "Incorrect password"}
    assert wrong not in response.text
    assert row_counts(migrated_db, person.id) == before
    assert client.get("/api/account", headers=person.headers).status_code == 200


@pytest.mark.parametrize("body", [{}, {"password": ""}, {"password": None}, {"password": 12345678},
                                  {"password": "secret-probe-" + "x" * 300}])
def test_delete_without_a_usable_password_is_422_without_echo_and_deletes_nothing(client, migrated_db, body):
    person = sign_up(client, migrated_db)
    give_everything(client, migrated_db, person)
    before = row_counts(migrated_db, person.id)
    response = delete_account(client, person, body)
    assert response.status_code == 422
    assert "secret-probe" not in response.text and "12345678" not in response.text
    for error in response.json()["detail"]:
        assert "input" not in error
    assert row_counts(migrated_db, person.id) == before


def test_delete_removes_the_users_rows_in_every_table_and_no_one_elses(client, migrated_db):
    alice, bob = sign_up(client, migrated_db), sign_up(client, migrated_db)
    give_everything(client, migrated_db, alice)
    give_everything(client, migrated_db, bob)
    bob_before = row_counts(migrated_db, bob.id)
    assert row_counts(migrated_db, alice.id) == {"users": 1, "skin_profiles": 2, "scan_history": 2, "subscriptions": 1}

    response = delete_account(client, alice)
    assert response.status_code == 204 and response.content == b""

    assert row_counts(migrated_db, alice.id) == {"users": 0, "skin_profiles": 0, "scan_history": 0, "subscriptions": 0}
    assert row_counts(migrated_db, bob.id) == bob_before
    assert client.get("/api/profile", headers=bob.headers).json()["id"] is not None
    assert len(client.get("/api/account/export", headers=bob.headers).json()["skin_profiles"]) == 2


def test_a_deleted_users_token_gets_401_everywhere(client, migrated_db):
    """Tokens are stateless and stay valid until they expire: the 401 comes from
    get_current_user finding no user. User ids are never reused, so a later signup
    can't inherit the old token."""
    person = sign_up(client, migrated_db)
    give_everything(client, migrated_db, person)
    assert delete_account(client, person).status_code == 204
    newcomer = sign_up(client, migrated_db)
    assert newcomer.id > person.id
    for method, path in [("GET", "/api/account"), ("GET", "/api/account/export"), ("GET", "/api/profile")]:
        assert client.request(method, path, headers=person.headers).status_code == 401, path
    assert delete_account(client, person).status_code == 401
    assert client.get("/api/account", headers=newcomer.headers).json()["email"] == newcomer.email


def test_a_token_for_a_user_deleted_outside_the_api_gets_401(client, migrated_db):
    person = sign_up(client, migrated_db)
    with migrated_db.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": person.id})
    assert client.get("/api/account", headers=person.headers).status_code == 401


def test_the_email_can_sign_up_again_after_deletion(client, migrated_db):
    person = sign_up(client, migrated_db)
    assert delete_account(client, person).status_code == 204
    again = client.post("/api/auth/register",
                        json={"email": person.email, "password": "another-password", "full_name": "Again"})
    assert again.status_code == 201
    login = client.post("/api/auth/login", json={"email": person.email, "password": person.password})
    assert login.status_code == 401  # the old password belonged to the deleted account


def test_nothing_about_the_account_is_logged(client, migrated_db, caplog):
    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.WARNING, logger="sqlalchemy")  # the test engine's own SQL echo, not the app's
    person = sign_up(client, migrated_db, "Logged Never")
    give_everything(client, migrated_db, person)
    with migrated_db.connect() as conn:
        stored_hash = conn.execute(text("SELECT hashed_password FROM users WHERE id = :u"), {"u": person.id}).scalar_one()
    client.get("/api/account", headers=person.headers)
    client.get("/api/account/export", headers=person.headers)
    delete_account(client, person, {"password": "wrong-" + person.password})
    delete_account(client, person)
    for secret in (person.email, person.password, stored_hash, "Logged Never", "prescription_retinoid"):
        assert secret not in caplog.text, secret


def test_the_export_states_what_isnt_stored():
    """What README/CLAUDE.md say the step 8 export must say."""
    statements = account.EXPORT_STATEMENTS
    assert set(statements) == {"photos", "answers", "chat", "chat_rate_limits", "logs", "password"}
    assert "no messages, answers or history" in statements["chat"]
    assert "only in the server's memory" in statements["chat_rate_limits"] and "restarts" in statements["chat_rate_limits"]
    assert "no user id and no text" in statements["logs"]
    assert "never saved" in statements["photos"]


def test_the_app_serves_the_account_endpoints():
    paths = main.app.openapi()["paths"]
    assert {"get", "delete"} <= set(paths["/api/account"]) and "get" in paths["/api/account/export"]
