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
    # The role the applicant selected on the single form's dropdown. Ingestion
    # routes the row to the job whose role_key matches this EXACTLY.
    role: Optional[str] = Field(None, description="Exact form dropdown role value.")
    job_id: Optional[str] = Field(None, description="Deprecated (per-job routing).")
    raw_row_data: dict[str, Any] = Field(default_factory=dict)


def _normalize_header(s: str) -> str:
    """Normalize a header (or FORM_ROLE_COLUMN) for tolerant matching.

    Google Form question titles routinely carry a trailing space and curly
    punctuation (e.g. the apostrophe ' U+2019), while a hand-typed / pasted
    ``FORM_ROLE_COLUMN`` often uses a straight ' and no trailing space. Match on
    a normalized form so those cosmetic differences don't cause a spurious
    "role column not detected": unify curly quotes to straight, collapse all
    whitespace runs, strip, and lowercase.
    """
    s = (
        s.replace("’", "'")  # ' right single quote
        .replace("‘", "'")  # ' left single quote
        .replace("“", '"')  # " left double quote
        .replace("”", '"')  # " right double quote
    )
    return " ".join(s.split()).lower()


def detect_role_column(headers: list[str]) -> str | None:
    """Find the role-question header among ``headers``.

    Uses ``FORM_ROLE_COLUMN`` (case-, whitespace- and smart-quote-insensitive)
    when set; if that env is set but not present in the sheet, returns None (a
    clear "not detected" so the intake-status endpoint can report it). Otherwise
    auto-detects the first header containing 'role'.
    """
    from app.config import get_form_role_column

    override = (get_form_role_column() or "").strip()
    if override:
        target = _normalize_header(override)
        for h in headers:
            if _normalize_header(h) == target:
                return h
        return None
    for h in headers:
        if "role" in h.strip().lower():
            return h
    return None


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
