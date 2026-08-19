"""Candidate repository contract + the stored record shape.

The repository is the seam that Phase 6 (Supabase) swaps behind. Callers depend
only on this Protocol, never on a concrete store.
"""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from app.models import Candidate, CandidateStatus, Evaluation, Job


class CandidateRecord(BaseModel):
    """A stored candidate: identity + evaluation + a pointer to parse artifacts.

    ``parsed_artifacts_dir`` is where the ``ParsedCV`` outputs (persisted PDF,
    rendered page images) live on disk, so later phases can re-read them without
    the store having to embed the full ``ParsedCV``.
    """

    candidate: Candidate
    evaluation: Optional[Evaluation] = None
    parsed_artifacts_dir: Optional[str] = None
    page_count: int = 0
    text_extraction_quality: Optional[str] = None

    # Stable artifact locations (Phase 4). Paths are relative to DATA_DIR and
    # served at /media/<...> — e.g. artifact_dir="candidates/<id>",
    # cv_file="cv.pdf", page_image_files=["page_1.png", "page_2.png"].
    artifact_dir: Optional[str] = None
    cv_file: Optional[str] = None
    page_image_files: list[str] = Field(default_factory=list)

    @property
    def overall_score(self) -> float:
        return self.evaluation.overall_score if self.evaluation else -1.0


@runtime_checkable
class CandidateRepository(Protocol):
    """Persistence for candidates + their evaluations."""

    def get_by_job_and_hash(
        self, job_id: str, file_hash: str
    ) -> Optional[Candidate]:
        """Return the stored candidate for this ``(job_id, file_hash)``, or None.

        Dedup is scoped per job: the same CV can apply to two openings, but
        re-running one job still skips its own duplicates.
        """
        ...

    def upsert(
        self,
        candidate: Candidate,
        parsed_cv: "object",  # app.models.ParsedCV; kept loose to avoid a hard import cycle
        evaluation: Optional[Evaluation],
        *,
        artifact_dir: Optional[str] = None,
        cv_file: Optional[str] = None,
        page_image_files: Optional[list[str]] = None,
    ) -> None:
        """Insert or replace the record for ``candidate``.

        The optional keyword args record stable artifact locations (relative to
        DATA_DIR) so the API can serve the CV + page images without re-parsing.
        """
        ...

    def get(self, candidate_id: str) -> Optional[CandidateRecord]:
        """Return the full record for ``candidate_id``, or None."""
        ...

    def list_all(self) -> list[CandidateRecord]:
        """Return all stored records (unordered)."""
        ...

    def list_by_job(
        self, job_id: str, status: Optional[CandidateStatus] = None
    ) -> list[CandidateRecord]:
        """Return records for ``job_id``, optionally filtered to a ``status``."""
        ...

    def update_status(self, candidate_id: str, status: CandidateStatus) -> None:
        """Update just the status of a stored candidate."""
        ...

    def update_decision(
        self, candidate_id: str, decision: str, note: Optional[str]
    ) -> CandidateRecord:
        """Record a human shortlist/reject decision + note; return the record.

        ``decision`` is ``"shortlist"`` or ``"reject"``; anything else is a
        ``ValueError``. Missing candidate is a ``KeyError``.
        """
        ...

    def record_assignment_sent(
        self, candidate_id: str, sent_at: "object", deadline: "object"
    ) -> CandidateRecord:
        """Mark an assignment as sent: status -> assignment_sent, set sent_at +
        deadline, increment the send count; return the record.

        ``sent_at`` is a ``datetime``, ``deadline`` a ``date``. Missing candidate
        is a ``KeyError``.
        """
        ...


@runtime_checkable
class JobRepository(Protocol):
    """Persistence for :class:`~app.models.Job` records.

    Same seam idea as :class:`CandidateRepository` — Phase 6 (Supabase) swaps the
    concrete store, callers depend only on this Protocol.
    """

    def add(self, job: Job) -> Job:
        """Insert (or replace) a job; return it. Raises ``ValueError`` on a
        duplicate id when the caller expects a fresh create."""
        ...

    def update(self, job: Job) -> Job:
        """Replace an existing job by id; return it. Raises ``KeyError`` if the
        id is not present."""
        ...

    def get(self, job_id: str) -> Optional[Job]:
        """Return the job with this id, or None."""
        ...

    def list_all(self) -> list[Job]:
        """Return all jobs (unordered)."""
        ...
