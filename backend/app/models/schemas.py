"""Pydantic v2 data models shared across the recruitment-screening pipeline.

These are the contract that later phases depend on. Scores are expressed on a
**0-100** scale everywhere (chosen once, applied consistently).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


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
    # Phase 16 (pdf_direct): the Drive file id the CV came from, so the PDF
    # viewer can fetch it on demand without local image storage. None for
    # fixture/local CVs (served from the persisted local PDF instead).
    cv_drive_file_id: Optional[str] = None
    # Portfolio / work-samples link from the application form (design/creative
    # roles). None when the form has no such field or the applicant left it blank.
    portfolio_url: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: CandidateStatus = CandidateStatus.parsed
    # Human review (Phase 4). Populated by the approval gate; None until decided.
    reviewer_note: Optional[str] = None
    decided_at: Optional[datetime] = None
    # Who made the shortlist/reject decision (full name of the acting user), for
    # per-user attribution ("Shortlisted by Abdul"). None until decided/undone.
    decided_by: Optional[str] = None
    # Assignment dispatch (Phase 5). Set when an assignment email is sent.
    assignment_sent_at: Optional[datetime] = None
    assignment_deadline: Optional[date] = None
    assignment_sent_count: int = 0
    # Full name of the user who sent the assignment (attribution).
    assignment_sent_by: Optional[str] = None


class ChatMessage(BaseModel):
    """One team-chat message. ``id`` is a monotonic sequence for cursor polling;
    ``full_name`` is stored so the history shows real names even if an account is
    later renamed."""

    id: int
    username: str
    full_name: str
    body: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


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


# The visual-design criterion that MUST exist whenever the "score visual design"
# toggle (``requires_visual_review``) is on — so the visual score is always
# produced and shown, not just when someone remembered to list it in the rubric.
VISUAL_CRITERION_NAME = "Visual hierarchy & layout"
VISUAL_CRITERION_WEIGHT = 3.0
VISUAL_CRITERION_DESCRIPTION = (
    "Quality of the CV's own visual hierarchy, layout, spacing, and section "
    "design — assessed from the page images, as a proxy for design craft."
)


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

    @model_validator(mode="after")
    def _ensure_visual_criterion(self) -> "Rubric":
        """When the visual-design toggle is on, guarantee the visual criterion is
        present. This is the invariant behind "toggle on => visual score shown":
        sending page images (requires_visual_review) is pointless if no criterion
        scores what they show, so we inject one when it's missing rather than
        silently drop the visual signal. Applied on every construction — API
        create/update, ingest, and load-from-store — so it can't be bypassed.
        """
        if not self.requires_visual_review:
            return self
        if any("visual" in c.name.lower() for c in self.criteria):
            return self
        self.criteria.insert(
            0,
            RubricCriterion(
                name=VISUAL_CRITERION_NAME,
                description=VISUAL_CRITERION_DESCRIPTION,
                weight=VISUAL_CRITERION_WEIGHT,
            ),
        )
        return self


class Job(BaseModel):
    """A hiring role: its job description + scoring rubric. Candidates are
    ingested and evaluated per-job."""

    id: str = Field(..., description="Stable job identifier (slug).")
    title: str
    job_description: str
    rubric: Rubric
    status: JobStatus = JobStatus.open
    # The exact dropdown value on the single application form that this job
    # serves (e.g. "Graphic Design Intern"). Ingestion routes each form row to a
    # job by an EXACT match on this — never a fuzzy/AI guess. Unique across jobs.
    # Defaults to "" only so legacy rows load; the create API requires a value.
    role_key: str = Field("", description="Exact form dropdown value this job serves.")
    google_sheet_id: Optional[str] = Field(
        None,
        description=(
            "DEPRECATED (Phase 15): per-job sheet routing is gone — the form is "
            "embedded once at site level (GOOGLE_SHEET_ID) and rows route by "
            "role_key. Column kept for back-compat; no longer read for ingestion."
        ),
    )
    # Assignment dispatch config (Phase 9). The brief file itself lives on disk
    # at data/jobs/{id}/assignment_brief.pdf; this holds the original filename.
    assignment_brief_filename: Optional[str] = None
    # The brief PDF bytes, stored in the DB so the file survives restarts (Render's
    # disk is ephemeral). Excluded from API responses + JSON serialization; the
    # SQL store maps it explicitly. None when no brief, or on the local disk-only
    # path. See app/pipeline/assignment.py for how it's resolved at send time.
    assignment_brief_data: Optional[bytes] = Field(default=None, exclude=True, repr=False)
    assignment_deadline_days: Optional[int] = Field(
        None, description="Days until the assignment deadline; None = env default."
    )
    assignment_message: Optional[str] = Field(
        None, description="Optional custom line added to the assignment email body."
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
