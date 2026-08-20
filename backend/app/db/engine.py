"""Engine + session plumbing for the Postgres store backend.

One :class:`~sqlalchemy.engine.Engine` is built lazily from ``DATABASE_URL`` and
cached (rebuilt only if the URL changes — e.g. across tests). ``pool_pre_ping``
is on and the pool is kept small because managed free tiers (Supabase) drop
idle connections; pre-ping transparently replaces a stale one instead of raising.

Callers use a session-per-operation pattern via :func:`session_scope` (or the
per-store scope), which commits on success and rolls back on any exception.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_database_url
from app.db.base import Base

# Import the models module for its side effect: registering the tables on
# ``Base.metadata`` so ``create_all`` and any engine-bound work see them.
from app.db import models as _models  # noqa: F401


class DatabaseConfigError(RuntimeError):
    """Raised when the Postgres backend is selected but misconfigured."""


_engine: Optional[Engine] = None
_Session: Optional[sessionmaker] = None
_engine_url: Optional[str] = None


def make_sessionmaker(engine: Engine) -> sessionmaker:
    """A sessionmaker with the settings the stores rely on.

    ``expire_on_commit=False`` lets a method read attributes off a row (to
    reconstruct the Pydantic record it returns) after the surrounding scope
    commits, without a second query.
    """
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)


def _build_engine(url: str) -> Engine:
    connect_args: dict = {}
    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        # In-memory/file SQLite is used only by the offline tests; allow it to
        # be shared across threads (TestClient/uvicorn workers).
        connect_args["check_same_thread"] = False
    else:
        # Small pool — the free tier caps connections; pre-ping handles drops.
        kwargs["pool_size"] = 5
        kwargs["max_overflow"] = 2
    return create_engine(url, connect_args=connect_args, **kwargs)


def get_engine() -> Engine:
    """Return the process-wide engine, building it from ``DATABASE_URL`` lazily.

    Raises :class:`DatabaseConfigError` (a clear, actionable message) when
    ``DATABASE_URL`` is unset — on first DB use, never at import.
    """
    global _engine, _Session, _engine_url
    url = get_database_url()
    if not url:
        raise DatabaseConfigError(
            "DATABASE_URL is not set. STORE_BACKEND=postgres requires a Postgres "
            "connection string (see the README 'Database (Supabase Postgres)' "
            "section), e.g. postgresql+psycopg2://USER:PASSWORD@HOST:5432/postgres"
        )
    if _engine is None or _engine_url != url:
        _engine = _build_engine(url)
        _Session = make_sessionmaker(_engine)
        _engine_url = url
    return _engine


def get_sessionmaker() -> sessionmaker:
    """Return the sessionmaker bound to the process-wide engine."""
    get_engine()
    assert _Session is not None
    return _Session


@contextmanager
def session_scope(session_factory: Optional[sessionmaker] = None) -> Iterator[Session]:
    """A transactional scope: commit on success, roll back on error, always close."""
    factory = session_factory or get_sessionmaker()
    session = factory()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def create_all(engine: Optional[Engine] = None) -> None:
    """Create any missing tables. Idempotent — safe to re-run."""
    Base.metadata.create_all(engine or get_engine())
