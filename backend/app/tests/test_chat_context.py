"""The chat's context through the real database path (7d, Unit 2): a sentinel user's email,
name and raw scores never reach the model's messages. Needs Docker (throwaway database)."""

import json
import uuid

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models import User
from app.services.chat.context import build_messages, load_profile_context
from app.services.chat.kb import load_kb

SCORES = {"acne_score": 87, "redness_score": 74, "wrinkle_score": 93, "pigmentation_score": 66, "pore_score": 81}


def test_the_prompt_never_holds_the_users_email_name_or_raw_scores(api, migrated_db):
    email = f"sentinel-{uuid.uuid4().hex[:10]}@example.com"
    name = "Zebediah Quillfeather-Sentinel"
    response = api.post("/api/auth/register",
                        json={"email": email, "password": "correct-horse-battery", "full_name": name})
    assert response.status_code == 201, response.text
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    response = api.post("/api/profile", headers=headers,
                        json={**SCORES, "skin_type": "oily", "is_sensitive": True})
    assert response.status_code == 201, response.text

    with sessionmaker(bind=migrated_db)() as db:
        user = db.scalars(select(User).where(User.email == email)).one()
        context = load_profile_context(db, user)
    kb = load_kb()
    built = build_messages("How often should I reapply sunscreen?", [], [kb.get("kb-sun-sunscreen-use")], context)
    blob = json.dumps(built.messages)

    assert context is not None and context.steps
    assert email not in blob and "sentinel-" not in blob
    assert name not in blob and "Zebediah" not in blob and "Quillfeather" not in blob
    for value in SCORES.values():
        assert f"({value})" not in blob and f" {value} " not in blob and f" {value}." not in blob
    assert "acne High" in blob and "Sensitive skin: yes" in blob


def test_a_user_without_a_profile_gets_general_answers(api, migrated_db, auth_headers):
    with sessionmaker(bind=migrated_db)() as db:
        user = db.scalars(select(User).order_by(User.id.desc())).first()
        assert load_profile_context(db, user) is None
