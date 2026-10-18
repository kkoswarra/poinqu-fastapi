"""Entry point API Poinqu (Fase 2).

Jalankan:
    uvicorn app.main:app --reload
Dokumentasi:
    /docs, /redoc, /openapi.json
"""

from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.core.errors import (
    AppError,
    app_error_handler,
    error_response,
    http_exception_handler,
    new_request_id,
    ok,
    request_id_ctx,
    unhandled_exception_handler,
    validation_error_handler,
)
from app.core.openapi import build_openapi
from app.db import SessionLocal, init_schema
from app.routers import admin, auth, me, recovery, webhooks
from app.services import email as email_service
from app.services import wa
from app.services.admin import ensure_seed

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger("poinqu")


@asynccontextmanager
async def lifespan(_: FastAPI):
    Path(settings.AVATAR_DIR).mkdir(parents=True, exist_ok=True)
    if settings.AUTO_CREATE_TABLES:
        init_schema()
    with SessionLocal() as db:
        ensure_seed(db)
    active_gateway = wa.get_gateway()
    logger.warning("OTP provider aktif: %s", active_gateway.name)
    if active_gateway.name == "FONNTE" and not settings.FONNTE_TOKEN:
        logger.error("FONNTE_TOKEN kosong: endpoint OTP akan membalas 503.")

    active_email = email_service.get_gateway()
    logger.warning("Email gateway aktif: %s", active_email.name)
    if active_email.name == "SMTP" and not settings.SMTP_HOST:
        logger.error("SMTP_HOST kosong: OTP email akan gagal.")
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="API dompet digital Poinqu — Fase 2 (auth, PIN, perangkat, biometrik, profil, admin).",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "Retry-After"],
)

app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)


def custom_openapi() -> dict:
    if app.openapi_schema:
        return app.openapi_schema
    app.openapi_schema = build_openapi(app)
    return app.openapi_schema


app.openapi = custom_openapi


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", value)[:3])


def _guard(request: Request) -> JSONResponse | None:
    path = request.url.path
    guarded = path == settings.API_PREFIX or path.startswith(settings.API_PREFIX + "/")
    if not guarded or path.startswith(settings.API_PREFIX + "/admin"):
        return None
    if path.startswith(settings.API_PREFIX + "/webhooks"):
        return None

    if not request.headers.get("X-Device-Id"):
        return error_response(
            "VALIDATION_ERROR",
            errors=[
                {
                    "field": "X-Device-Id",
                    "code": "REQUIRED",
                    "message": "Wajib diisi.",
                }
            ],
        )

    if settings.MIN_APP_VERSION:
        app_version = request.headers.get("X-App-Version")
        if app_version and _version_tuple(app_version) < _version_tuple(settings.MIN_APP_VERSION):
            return error_response("UPGRADE_REQUIRED", status=426)
    return None


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = new_request_id()
    request_id_ctx.set(request_id)

    guard_response = _guard(request) if request.method != "OPTIONS" else None
    response = guard_response if guard_response is not None else await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


app.include_router(auth.router, prefix=settings.API_PREFIX)
app.include_router(recovery.router, prefix=settings.API_PREFIX)
app.include_router(me.router, prefix=settings.API_PREFIX)
app.include_router(admin.router, prefix=settings.API_PREFIX)
app.include_router(webhooks.router, prefix=settings.API_PREFIX)

Path(settings.AVATAR_DIR).parent.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(Path(settings.AVATAR_DIR).parent)), name="media")


@app.get("/health", tags=["system"], summary="Health check")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "environment": settings.ENVIRONMENT,
        "version": settings.APP_VERSION,
    }


@app.get("/", tags=["system"], summary="Info API")
def root() -> dict:
    return ok(
        {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "docs": "/docs",
            "api_prefix": settings.API_PREFIX,
        }
    )
