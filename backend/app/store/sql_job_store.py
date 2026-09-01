"""Postgres-backed :class:`~app.store.base.JobRepository` (SQLAlchemy).

Method-for-method equivalent of :class:`~app.store.job_store.JSONJobRepository`,
so callers behind the protocol see identical behavior. A session is opened per
operation and committed/rolled back cleanly.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy.engine import Engine

from app.db.engine import get_sessionmaker, make_sessionmaker, session_scope
from app.db.models import JobRow
from app.models import Job, Rubric


def _enum_value(v) -> str:
    """The stored string for an enum-or-str field (tolerant like model_dump)."""
    return v.value if isinstance(v, Enum) else str(v)


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Return a tz-aware UTC datetime. We always persist UTC, so a naive value
    read back (SQLite drops tzinfo) is interpreted as UTC — keeping parity with
    the JSON store, which round-trips tz-aware ISO strings."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _to_job(row: JobRow) -> Job:
    return Job(
        id=row.id,
        title=row.title,
        job_description=row.job_description,
        rubric=Rubric.model_validate(row.rubric),
        status=row.status,
        role_key=row.role_key or "",
        google_sheet_id=row.google_sheet_id,
        assignment_brief_filename=row.assignment_brief_filename,
        assignment_brief_data=row.assignment_brief_data,
        assignment_deadline_days=row.assignment_deadline_days,
        assignment_message=row.assignment_message,
        created_at=_as_utc(row.created_at),
    )


def _apply(row: JobRow, job: Job) -> None:
    row.id = job.id
    row.title = job.title
    row.job_description = job.job_description
    row.rubric = job.rubric.model_dump(mode="json")
    row.status = _enum_value(job.status)
    row.role_key = job.role_key or ""
    row.google_sheet_id = job.google_sheet_id
    row.assignment_brief_filename = job.assignment_brief_filename
    row.assignment_brief_data = job.assignment_brief_data
    row.assignment_deadline_days = job.assignment_deadline_days
    row.assignment_message = job.assignment_message
    row.created_at = job.created_at


class SQLJobRepository:
    """A ``JobRepository`` backed by the ``jobs`` table."""

    def __init__(self, engine: Engine | None = None) -> None:
        # Injected engine (tests) gets its own sessionmaker; otherwise defer to
        # the process-wide one, resolved lazily so import never needs a DB.
        self._sessionmaker = make_sessionmaker(engine) if engine is not None else None

    def _scope(self):
        return session_scope(self._sessionmaker or get_sessionmaker())

    def add(self, job: Job) -> Job:
        with self._scope() as s:
            if s.get(JobRow, job.id) is not None:
                raise ValueError(f"Job id {job.id!r} already exists.")
            row = JobRow()
            _apply(row, job)
            s.add(row)
        return job

    def update(self, job: Job) -> Job:
        with self._scope() as s:
            row = s.get(JobRow, job.id)
            if row is None:
                raise KeyError(f"No job with id {job.id!r}")
            _apply(row, job)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._scope() as s:
            row = s.get(JobRow, job_id)
            return _to_job(row) if row is not None else None

    def list_all(self) -> list[Job]:
        with self._scope() as s:
            return [_to_job(r) for r in s.query(JobRow).all()]
