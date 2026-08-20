"""Store factories.

Return the JSON stores by default; return the SQLAlchemy/Postgres stores when
``STORE_BACKEND=postgres``. The backend is read at call time, and the SQL layer
is imported lazily so the JSON default never needs SQLAlchemy at import. This is
the ENTIRE wiring change — no caller touches a concrete store.
"""
from __future__ import annotations

from app.config import get_store_backend
from app.store.base import CandidateRepository, JobRepository
from app.store.job_store import JSONJobRepository
from app.store.json_store import JSONCandidateStore


def get_candidate_store() -> CandidateRepository:
    if get_store_backend() == "postgres":
        from app.store.sql_candidate_store import SQLCandidateStore

        return SQLCandidateStore()
    return JSONCandidateStore()


def get_job_repository() -> JobRepository:
    if get_store_backend() == "postgres":
        from app.store.sql_job_store import SQLJobRepository

        return SQLJobRepository()
    return JSONJobRepository()
