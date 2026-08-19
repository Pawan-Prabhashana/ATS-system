"""Pydantic v2 data models shared across the recruitment-screening pipeline.

These are the contract that later phases depend on. Scores are expressed on a
**0-100** scale everywhere (chosen once, applied consistently).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class CandidateStatus(str, Enum):
    """Lifecycle of a candidate across all phases.

    Only ``parsed`` and ``scored`` are produced in Phase 1; the rest are
    defined now so later phases don't need a schema migration.
    """

    parsed = "parsed"
    scored = "scored"
    shortlisted = "shortlisted"
    assignment_sent = "assignment_sent"
    submitted = "submitted"
    rejected = "rejected"


class TextExtractionQuality(str, Enum):
    """Whether pdfplumber recovered enough text to trust the text layer."""

    ok = "ok"
    low = "low"  # likely a scanned / image-only CV -> rely on page images


class Recommendation(str, Enum):
    shortlist = "shortlist"
    borderline = "borderline"
    reject = "reject"


class JobStatus(str, Enum):
    open = "open"
    closed = "closed"


# --------------------------------------------------------------------------- #
# Candidate & parsing models
# --------------------------------------------------------------------------- #
class Candidate(BaseModel):
    id: str = Field(..., description="Stable candidate identifier.")
    # Which job this candidate applied to. Empty at parse time; the ingestion
    # pipeline assigns it (candidates are always ingested under a specific job).
    job_id: str = ""
    name: Optional[str] = None
    email: Optional[str] = None
    source_form_row: Optional[int] = Field(
        None, description="Row index in the source Google Form responses sheet."
    )
    cv_filename: str
    file_hash: str = Field(..., description="SHA-256 of the raw PDF bytes; used for dedup.")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: CandidateStatus = CandidateStatus.parsed
    # Human review (Phase 4). Populated by the approval gate; None until decided.
    reviewer_note: Optional[str] = None
    decided_at: Optional[datetime] = None
    # Assignment dispatch (Phase 5). Set when an assignment email is sent.
    assignment_sent_at: Optional[datetime] = None
    assignment_deadline: Optional[date] = None
    assignment_sent_count: int = 0


class PageImage(BaseModel):
    page_number: int = Field(..., ge=1, description="1-based page index.")
    image_path: str = Field(..., description="Filesystem path to the rendered PNG.")
    width: int = Field(..., ge=0)
    height: int = Field(..., ge=0)


class PageText(BaseModel):
    page_number: int = Field(..., ge=1)
    text: str = ""


class ParsedCV(BaseModel):
    candidate_id: str
    raw_text: str = Field("", description="Full concatenated text of the document.")
    pages: list[PageText] = Field(default_factory=list)
    page_images: list[PageImage] = Field(default_factory=list)
    page_count: int = Field(0, ge=0)
    text_extraction_quality: TextExtractionQuality = TextExtractionQuality.ok
    parser_warnings: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Rubric & evaluation models
# --------------------------------------------------------------------------- #
class RubricCriterion(BaseModel):
    name: str
    description: str = ""
    weight: float = Field(..., gt=0, description="Relative weight; need not sum to 1.")


class Rubric(BaseModel):
    job_title: str = ""
    criteria: list[RubricCriterion] = Field(..., min_length=1)
    requires_visual_review: bool = Field(
        False,
        description=(
            "When True, the evaluator sends CV page images to the vision model "
            "and scores visual hierarchy/formatting. When False, text-only "
            "(no image payload) — the cost/latency saving. Set True for roles "
            "where document design matters (e.g. design/brand)."
        ),
    )


class Job(BaseModel):
    """A hiring role: its job description + scoring rubric. Candidates are
    ingested and evaluated per-job."""

    id: str = Field(..., description="Stable job identifier (slug).")
    title: str
    job_description: str
    rubric: Rubric
    status: JobStatus = JobStatus.open
    google_sheet_id: Optional[str] = Field(
        None,
        description=(
            "Responses Sheet ID for this job's Google Form. None = not connected "
            "to a live form yet (ingestion falls back to local fixtures)."
        ),
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CriterionScore(BaseModel):
    criterion_name: str
    score: float = Field(..., ge=0, le=100, description="0-100 scale.")
    weight: float = Field(..., gt=0)
    evidence: str = Field(
        "", description="Quote/paraphrase from the CV supporting the score."
    )


class Evaluation(BaseModel):
    candidate_id: str
    criterion_scores: list[CriterionScore] = Field(default_factory=list)
    overall_score: float = Field(..., ge=0, le=100, description="0-100 weighted score.")
    recommendation: Recommendation
    summary: str = ""
    evaluated_by: str = Field(..., description="Identifier of the evaluator, e.g. 'mock'.")
