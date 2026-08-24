"""FastAPI application factory."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.auth import require_auth
from app.auth import router as auth_router
from app.config import settings

# Dev origins allowed to call the API (the Next.js dev server). Overridable via
# a comma-separated CATALIST_CORS_ORIGINS for other setups. The frontend has run
# on :3000 and :3009 across phases, so both are allowed by default.
DEFAULT_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3009",
    "http://127.0.0.1:3009",
]


def _cors_origins() -> list[str]:
    raw = os.getenv("CATALIST_CORS_ORIGINS")
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return DEFAULT_CORS_ORIGINS


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # On the Postgres backend, ensure the schema exists before anything reads
    # or writes it (idempotent create_all). Fires only when an ASGI server runs
    # the lifespan — NOT on a bare TestClient(app) instantiation.
    try:
        from app.config import get_store_backend

        if get_store_backend() == "postgres":
            from app.db.engine import create_all

            create_all()
    except Exception as exc:  # pragma: no cover - startup convenience only
        print(f"[startup] schema bootstrap skipped: {exc}")

    # Seed the sample jobs on real server start if the job store is empty. This
    # fires only when an ASGI server runs the lifespan — NOT on a bare
    # TestClient(app) instantiation — so tests manage their own job stores.
    try:
        from app.store import ensure_jobs_seeded, get_job_repository

        ensure_jobs_seeded(get_job_repository())
    except Exception as exc:  # pragma: no cover - startup convenience only
        print(f"[startup] job seeding skipped: {exc}")
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Catalist Recruit Screening",
        version="0.5.0",
        description="Phases 1-5: parsing, evaluation, multi-job ingestion, review, email.",
        lifespan=_lifespan,
    )

    # allow_credentials=True with an EXACT origin allowlist (never "*"). We use
    # Bearer tokens (not cookies), so explicit methods/headers keep this valid
    # under the credentialed-CORS rules (where "*" is disallowed).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "PUT", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:  # public — the one unauthenticated route
        return {"status": "ok"}

    # Auth routes are reachable WITHOUT a session (login must be); every other
    # route is gated by require_auth.
    app.include_router(auth_router)
    app.include_router(router, dependencies=[Depends(require_auth)])

    # Serve per-candidate artifacts (CV + page images) as static files so the
    # frontend can load them by URL. Directory is created if missing.
    media_dir = settings.data_dir / "candidates"
    media_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/media/candidates",
        StaticFiles(directory=str(media_dir)),
        name="media-candidates",
    )

    return app


app = create_app()
