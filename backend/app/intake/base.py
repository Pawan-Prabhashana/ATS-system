"""Intake source contract.

An ``IntakeSource`` yields raw candidate submissions and can download the CV
file behind each one. Concrete sources: ``LocalFixtureIntakeSource`` (offline
CSV) and ``GoogleFormsIntakeSource`` (Sheets + Drive).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class RawSubmission(BaseModel):
    """A single form submission, before parsing/evaluation.

    ``cv_file_ref`` is source-specific: a filename for the local fixture, a
    Drive file id for Google Forms. Callers pass it back to ``download_cv``.
    """

    name: Optional[str] = None
    email: Optional[str] = None
    submitted_at: Optional[datetime] = None
    cv_file_ref: str = Field(..., description="Source-specific pointer to the CV file.")
    job_id: Optional[str] = Field(None, description="Which job this submission is for.")
    raw_row_data: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class IntakeSource(Protocol):
    """Fetches new submissions and downloads their CV files."""

    name: str

    def fetch_new_submissions(
        self, job_id: str | None = None
    ) -> list[RawSubmission]:
        """Return submissions to consider for ingestion.

        When ``job_id`` is given, return only submissions for that job; when
        ``None``, return all. Sources need not track "seen" state themselves —
        the ingestion pipeline dedups by file hash, so returning all matching
        rows on each call is safe.
        """
        ...

    def download_cv(self, submission: RawSubmission, dest_dir: Path) -> Path:
        """Fetch the CV for ``submission`` into ``dest_dir``; return its path."""
        ...
