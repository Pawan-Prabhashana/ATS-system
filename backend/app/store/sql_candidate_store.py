"""Postgres-backed :class:`~app.store.base.CandidateRepository` (SQLAlchemy).

Method-for-method equivalent of :class:`~app.store.json_store.JSONCandidateStore`
— every dedup key, filter, decision/undo rule and assignment update below mirrors
the JSON store exactly, so callers behind the protocol cannot tell them apart.
The reviewer-decision status mapping is imported from the JSON store so the two
backends can never drift.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from sqlalchemy.engine import Engine

from app.db.engine import get_sessionmaker, make_sessionmaker, session_scope
from app.db.models import CandidateRow
from app.models import Candidate, CandidateStatus, Evaluation, ParsedCV
from app.store.base import CandidateRecord

# Single-sourced so the SQL and JSON backends map decisions identically.
from app.store.json_store import _DECISION_STATUS


def _enum_value(v) -> str:
    """The stored string for an enum-or-str field (tolerant like model_dump)."""
    return v.value if isinstance(v, Enum) else str(v)


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """See :func:`app.store.sql_job_store._as_utc` — persisted values are UTC."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _to_candidate(row: CandidateRow) -> Candidate:
    return Candidate(
        id=row.id,
        job_id=row.job_id,
        name=row.name,
        email=row.email,
        source_form_row=row.source_form_row,
        cv_filename=row.cv_filename,
        cv_drive_file_id=row.cv_drive_file_id,
        portfolio_url=row.portfolio_url,
        file_hash=row.file_hash,
        created_at=_as_utc(row.created_at),
        status=row.status,
        reviewer_note=row.reviewer_note,
        decided_at=_as_utc(row.decided_at),
        assignment_sent_at=_as_utc(row.assignment_sent_at),
        assignment_deadline=row.assignment_deadline,
        assignment_sent_count=row.assignment_sent_count,
    )


def _to_record(row: CandidateRow) -> CandidateRecord:
    evaluation = Evaluation.model_validate(row.evaluation) if row.evaluation else None
    return CandidateRecord(
        candidate=_to_candidate(row),
        evaluation=evaluation,
        parsed_artifacts_dir=row.parsed_artifacts_dir,
        page_count=row.page_count,
        text_extraction_quality=row.text_extraction_quality,
        artifact_dir=row.artifact_dir,
        cv_file=row.cv_file,
        page_image_files=list(row.page_image_files or []),
    )


def _apply_candidate(row: CandidateRow, candidate: Candidate) -> None:
    """Write every Candidate field onto the row (upsert fully replaces)."""
    row.id = candidate.id
    row.job_id = candidate.job_id
    row.file_hash = candidate.file_hash
    row.name = candidate.name
    row.email = candidate.email
    row.source_form_row = candidate.source_form_row
    row.cv_filename = candidate.cv_filename
    row.cv_drive_file_id = candidate.cv_drive_file_id
    row.portfolio_url = candidate.portfolio_url
    row.created_at = candidate.created_at
    row.status = _enum_value(candidate.status)
    row.reviewer_note = candidate.reviewer_note
    row.decided_at = candidate.decided_at
    row.assignment_sent_at = candidate.assignment_sent_at
    row.assignment_deadline = candidate.assignment_deadline
    row.assignment_sent_count = candidate.assignment_sent_count


class SQLCandidateStore:
    """A ``CandidateRepository`` backed by the ``candidates`` table."""

    def __init__(self, engine: Engine | None = None) -> None:
        self._sessionmaker = make_sessionmaker(engine) if engine is not None else None

    def _scope(self):
        return session_scope(self._sessionmaker or get_sessionmaker())

    # -- reads ------------------------------------------------------------- #
    def get_by_job_and_hash(
        self, job_id: str, file_hash: str
    ) -> Optional[Candidate]:
        with self._scope() as s:
            row = (
                s.query(CandidateRow)
                .filter(CandidateRow.job_id == job_id, CandidateRow.file_hash == file_hash)
                .first()
            )
            return _to_candidate(row) if row is not None else None

    def get(self, candidate_id: str) -> Optional[CandidateRecord]:
        with self._scope() as s:
            row = s.get(CandidateRow, candidate_id)
            return _to_record(row) if row is not None else None

    def list_all(self) -> list[CandidateRecord]:
        with self._scope() as s:
            return [_to_record(r) for r in s.query(CandidateRow).all()]

    def list_by_job(
        self, job_id: str, status: Optional[CandidateStatus] = None
    ) -> list[CandidateRecord]:
        with self._scope() as s:
            q = s.query(CandidateRow).filter(CandidateRow.job_id == job_id)
            if status is not None:
                q = q.filter(CandidateRow.status == status.value)
            return [_to_record(r) for r in q.all()]

    # -- writes ------------------------------------------------------------ #
    def upsert(
        self,
        candidate: Candidate,
        parsed_cv: ParsedCV | None,
        evaluation: Optional[Evaluation],
        *,
        artifact_dir: Optional[str] = None,
        cv_file: Optional[str] = None,
        page_image_files: Optional[list[str]] = None,
    ) -> None:
        # Derive artifact metadata exactly as the JSON store does.
        parsed_artifacts_dir = None
        page_count = 0
        quality = None
        if parsed_cv is not None:
            page_count = parsed_cv.page_count
            quality = parsed_cv.text_extraction_quality.value
            if parsed_cv.page_images:
                parsed_artifacts_dir = str(
                    Path(parsed_cv.page_images[0].image_path).parent.parent
                )

        with self._scope() as s:
            row = s.get(CandidateRow, candidate.id)
            if row is None:
                row = CandidateRow()
                s.add(row)
            _apply_candidate(row, candidate)
            row.evaluation = evaluation.model_dump(mode="json") if evaluation else None
            row.parsed_artifacts_dir = parsed_artifacts_dir
            row.page_count = page_count
            row.text_extraction_quality = quality
            row.artifact_dir = artifact_dir
            row.cv_file = cv_file
            row.page_image_files = list(page_image_files or [])

    def put_record(self, record: CandidateRecord) -> None:
        """Persist a full stored record verbatim (insert or replace by id).

        Not part of the repository protocol — used by the JSON->Postgres importer
        to carry over fields the protocol ``upsert`` would recompute from a
        ``parsed_cv`` it no longer has (page_count, text_extraction_quality,
        parsed_artifacts_dir).
        """
        with self._scope() as s:
            row = s.get(CandidateRow, record.candidate.id)
            if row is None:
                row = CandidateRow()
                s.add(row)
            _apply_candidate(row, record.candidate)
            row.evaluation = (
                record.evaluation.model_dump(mode="json") if record.evaluation else None
            )
            row.parsed_artifacts_dir = record.parsed_artifacts_dir
            row.page_count = record.page_count
            row.text_extraction_quality = record.text_extraction_quality
            row.artifact_dir = record.artifact_dir
            row.cv_file = record.cv_file
            row.page_image_files = list(record.page_image_files or [])

    def update_status(self, candidate_id: str, status: CandidateStatus) -> None:
        with self._scope() as s:
            row = s.get(CandidateRow, candidate_id)
            if row is None:
                raise KeyError(f"No candidate with id {candidate_id!r}")
            row.status = _enum_value(status)

    def update_decision(
        self, candidate_id: str, decision: str, note: Optional[str]
    ) -> CandidateRecord:
        # Validate the decision BEFORE touching the DB — same order as JSON
        # (an invalid decision is a ValueError even if the candidate is missing).
        status = _DECISION_STATUS.get(decision)
        if status is None:
            raise ValueError(
                f"Invalid decision {decision!r}; expected 'shortlist', 'reject', "
                "or 'undecided'."
            )
        with self._scope() as s:
            row = s.get(CandidateRow, candidate_id)
            if row is None:
                raise KeyError(f"No candidate with id {candidate_id!r}")
            row.status = status.value
            if decision == "undecided":
                # Clean undo — wipe the decision metadata too.
                row.reviewer_note = None
                row.decided_at = None
            else:
                row.reviewer_note = note
                row.decided_at = datetime.now(timezone.utc)
            return _to_record(row)

    def record_assignment_sent(
        self, candidate_id: str, sent_at: datetime, deadline: date
    ) -> CandidateRecord:
        with self._scope() as s:
            row = s.get(CandidateRow, candidate_id)
            if row is None:
                raise KeyError(f"No candidate with id {candidate_id!r}")
            row.status = CandidateStatus.assignment_sent.value
            row.assignment_sent_at = sent_at
            row.assignment_deadline = deadline
            row.assignment_sent_count = (row.assignment_sent_count or 0) + 1
            return _to_record(row)
