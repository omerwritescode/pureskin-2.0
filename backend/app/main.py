import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api import auth, catalog, image_analysis, profile, routine, scan
from app.core.config import settings
from app.services import image_analysis as image_analysis_service

logger = logging.getLogger("uvicorn.error")

# Absolute, so it works whatever directory uvicorn is started from.
# backend/app/main.py -> parent = app/, parent.parent = backend/, then up to the repo root.
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load AI models once at startup, not per request. A missing model disables only
    # that service (its endpoint returns 503 with the fix), not the whole app.
    try:
        analyzer = image_analysis_service.load_models()
        logger.info("Image Analysis: %s", analyzer.skin_type_status)
    except image_analysis_service.ModelUnavailable as exc:
        logger.error("Image Analysis service unavailable: %s", exc)
    yield


app = FastAPI(title="PureSkin API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(scan.router)
app.include_router(profile.router)
app.include_router(routine.router)
app.include_router(catalog.router)
app.include_router(image_analysis.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# Product detail pages have a dynamic id (/app/catalog/42/), which static files can't
# express, so every id serves the same page. ":int" so only numeric paths match and
# the page's own assets (/app/catalog/catalog.js, ...) still fall through to static files.
@app.get("/app/catalog/{product_id:int}/", include_in_schema=False)
def product_detail_page(product_id: int) -> FileResponse:
    return FileResponse(FRONTEND_DIR / "pages" / "app" / "catalog" / "detail" / "index.html")


@app.get("/app/catalog/{product_id:int}", include_in_schema=False)
def product_detail_redirect(product_id: int) -> RedirectResponse:
    return RedirectResponse(f"/app/catalog/{product_id}/")


# Serve the frontend from the same origin so pages live at their sitemap URLs
# (/auth/, /app/, /scan/, ...). Mounted last so API routes above take precedence.
app.mount("/static", StaticFiles(directory=FRONTEND_DIR / "static"), name="static")
app.mount("/", StaticFiles(directory=FRONTEND_DIR / "pages", html=True), name="pages")
