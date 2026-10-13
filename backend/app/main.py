import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api import (
    auth,
    catalog,
    chat,
    image_analysis,
    profile,
    questionnaire,
    routine,
    scan_analyze,
)
from app.api.validation_errors import public_errors
from app.core.config import settings
from app.services import image_analysis as image_analysis_service

logger = logging.getLogger("uvicorn.error")

# The app's own log lines (the chat's one metadata line per request): uvicorn configures
# only its own loggers, so without a handler these INFO lines would go nowhere.
_app_log = logging.getLogger("pureskin")
if not _app_log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
    _app_log.addHandler(_handler)
    _app_log.setLevel(logging.INFO)

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
    # The chat's model: checked in the background (1 s timeouts), so startup never waits on
    # Ollama, and never warmed (only /api/version and /api/tags).
    chat_probe = asyncio.create_task(chat.probe_chat())
    yield
    chat_probe.cancel()
    with suppress(asyncio.CancelledError, Exception):  # its outcome was logged (or it never finished)
        await chat_probe
    await chat.close_chat_llm()


app = FastAPI(title="PureSkin API", lifespan=lifespan)


# Every endpoint's 422: same {"detail": [{loc, msg, type}]} shape as FastAPI's default,
# but never the submitted input (the default echoes it: passwords, emails, free text).
# ctx is kept only for numeric limits (min_length, max_length, ge, le, gt, lt).
# Nothing about the request or its errors is logged.
@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": public_errors(exc.errors())},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(scan_analyze.router)
app.include_router(profile.router)
app.include_router(routine.router)
app.include_router(catalog.router)
app.include_router(image_analysis.router)
app.include_router(questionnaire.router)
app.include_router(chat.router)


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
