"""POST /api/chat through real sign-in and the real profile loader (7d, Unit 3), with the
fake model. Needs Docker (throwaway database)."""

import json
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api import auth, profile
from app.api import chat as chat_api
from app.api.deps import get_db
from app.services.chat.tests.fakes import FakeLLM

SCORES = {"acne_score": 87, "redness_score": 74, "wrinkle_score": 93, "pigmentation_score": 66, "pore_score": 81}


def test_a_signed_in_user_gets_an_answer_grounded_in_their_profile(migrated_db):
    Session = sessionmaker(bind=migrated_db, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    llm = FakeLLM(["Reapply at least every two hours [kb-sun-sunscreen-use]. "])
    app = FastAPI()
    for module in (auth, profile, chat_api):
        app.include_router(module.router)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[chat_api.get_chat_llm] = lambda: llm
    client = TestClient(app)

    email = f"chat-{uuid.uuid4().hex[:10]}@example.com"
    response = client.post("/api/auth/register",
                           json={"email": email, "password": "correct-horse-battery", "full_name": "Chat Sentinel"})
    assert response.status_code == 201, response.text
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

    assert client.post("/api/chat", json={"message": "How often should I reapply sunscreen?"}).status_code == 401

    # No scan yet: general answers only.
    response = client.post("/api/chat", headers=headers, json={"message": "How often should I reapply sunscreen?"})
    assert response.status_code == 200
    assert llm.calls[-1][1]["content"].startswith("PROFILE: none yet")

    response = client.post("/api/profile", headers=headers, json={**SCORES, "skin_type": "oily", "is_sensitive": True})
    assert response.status_code == 201, response.text
    response = client.post("/api/chat", headers=headers, json={"message": "How often should I reapply sunscreen?"})
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[0]["route"] == "model" and events[-1] == {"type": "end", "reason": "answered"}
    prompt = json.dumps(llm.calls[-1])
    assert "acne High" in prompt and "Sensitive skin: yes" in prompt
    assert email not in prompt and "Chat Sentinel" not in prompt and "(87)" not in prompt
