from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import auth, scan
from app.core.config import settings

# Absolute, so it works whatever directory uvicorn is started from.
# backend/app/main.py -> parent = app/, parent.parent = backend/, then up to the repo root.
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

app = FastAPI(title="PureSkin API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(scan.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# Serve the frontend from the same origin so pages live at their sitemap URLs
# (/auth/, /app/, /scan/, ...). Mounted last so API routes above take precedence.
app.mount("/static", StaticFiles(directory=FRONTEND_DIR / "static"), name="static")
app.mount("/", StaticFiles(directory=FRONTEND_DIR / "pages", html=True), name="pages")
