"""SQLAlchemy ORM tables mirroring the Pydantic store records.

Portability is deliberate: every column type here works identically on Postgres
and SQLite, so the same models back the production Postgres store and the
offline SQLite parity tests. In particular we use SQLAlchemy's generic ``JSON``
type (NOT Postgres ``JSONB``) and plain ``String``/``Text``/``Integer``/
``DateTime``/``Date`` — no dialect-specific types.

Only the *structured* records live here. Binary artifacts (the stored CV PDF and
rendered page images) STAY on the local filesystem under ``data/candidates/{id}/``
and keep being served by StaticFiles; the columns below hold only their relative
paths. Moving those blobs to object storage (e.g. Supabase Storage) is explicitly
future work, out of scope for this phase.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class JobRow(Base):
    """A hiring role. Mirrors :class:`app.models.Job` — the whole ``Rubric``
    (criteria + ``requires_visual_review``) is stored as one JSON column."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # the slug
    title: Mapped[str] = mapped_column(String, nullable=False)
    job_description: Mapped[str] = mapped_column(Text, nullable=False)
    rubric: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    # Phase 15: exact form dropdown value this job serves (routing key).
    role_key: Mapped[str] = mapped_column(String, nullable=False, default="")
    google_sheet_id: Mapped[str | None] = mapped_column(String, nullable=True)
    assignment_brief_filename: Mapped[str | None] = mapped_column(String, nullable=True)
    assignment_brief_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)  # brief PDF (persists restarts)
    assignment_deadline_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assignment_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CandidateRow(Base):
    """A stored candidate + its evaluation + artifact pointers.

    The primary key is the candidate id, which the ingestion pipeline derives
    from ``(job_id, file_hash)`` — so ``GET /candidates/{id}`` keeps resolving.
    A UNIQUE constraint on ``(job_id, file_hash)`` enforces the existing per-job
    dedup at the database level. The evaluation is stored whole as one JSON
    column (it is always read/written as a unit — criterion scores are NOT
    normalised into their own table).
    """

    __tablename__ = "candidates"
    __table_args__ = (
        UniqueConstraint("job_id", "file_hash", name="uq_candidates_job_file_hash"),
    )

    # -- Candidate identity + lifecycle (mirrors app.models.Candidate) ------- #
    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    file_hash: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    source_form_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cv_filename: Mapped[str] = mapped_column(String, nullable=False)
    cv_drive_file_id: Mapped[str | None] = mapped_column(String, nullable=True)  # Phase 16 pdf_direct
    cv_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)  # manual-upload CV (persists restarts)
    portfolio_url: Mapped[str | None] = mapped_column(String, nullable=True)  # portfolio / work-samples link
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String, nullable=True)  # attribution
    assignment_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assignment_deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    assignment_sent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    assignment_sent_by: Mapped[str | None] = mapped_column(String, nullable=True)  # attribution

    # -- Evaluation (whole Evaluation as one JSON blob) ---------------------- #
    evaluation: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # -- Parse artifacts (paths only; blobs stay on the filesystem) ---------- #
    parsed_artifacts_dir: Mapped[str | None] = mapped_column(String, nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    text_extraction_quality: Mapped[str | None] = mapped_column(String, nullable=True)
    artifact_dir: Mapped[str | None] = mapped_column(String, nullable=True)
    cv_file: Mapped[str | None] = mapped_column(String, nullable=True)
    page_image_files: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


class UserRow(Base):
    """A reviewer account. Individual logins let the system attribute each
    shortlist/reject/assignment to the person who did it. Passwords are stored
    only as a pbkdf2 hash (see app.users); plaintext never touches the DB."""

    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String, primary_key=True)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IngestSkipRow(Base):
    """A form submission that can't be scored (non-PDF/corrupt/unreadable upload).
    Recorded so a re-pull skips it instead of re-attempting (and re-crashing) it."""

    __tablename__ = "ingest_skips"
    __table_args__ = (
        UniqueConstraint("job_id", "drive_file_id", name="uq_ingest_skips_job_file"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    drive_file_id: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChatMessageRow(Base):
    """One team-chat message. Monotonic integer id doubles as the poll cursor."""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String, nullable=False)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
