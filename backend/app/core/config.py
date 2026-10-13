"""Application settings, loaded from the repo-root .env via python-dotenv."""

import os
from pathlib import Path

from dotenv import load_dotenv

# backend/app/core/config.py -> repo root is three levels above this file's folder
ROOT_DIR = Path(__file__).resolve().parents[3]
load_dotenv(ROOT_DIR / ".env")


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable {name!r}. "
            "Copy .env.example to .env and fill it in."
        )
    return value


class Settings:
    DATABASE_URL: str = _require("DATABASE_URL")
    SECRET_KEY: str = _require("SECRET_KEY")
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
    CORS_ORIGINS: list[str] = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:5500").split(",")
        if origin.strip()
    ]
    # Chat (7d), optional: without them the chat is unavailable (503), the rest of the app
    # isn't affected. OLLAMA_HOST must be a loopback address; CHAT_MODEL must be pinned in
    # app/services/chat/chat_config.py (ALLOWED_MODELS).
    OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "")
    CHAT_MODEL: str = os.getenv("CHAT_MODEL", "")


settings = Settings()
