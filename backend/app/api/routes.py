"""FastAPI routes: parsing core (Phase 1) + ingestion/listing/review (Phase 3-4)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.email.factory import get_email_sender
from app.models import (
    Candidate,
    CandidateStatus,
    Evaluation,
    Job,
    ParsedCV,
    Recommendation,
    Rubric,
)
from app.parsing import parse_cv_bytes
from app.pipeline import IngestionSummary, run_ingestion
from app.pipeline.assignment import (
    BulkSendResult,
    SendOutcomeStatus,
    bulk_send_assignments,
    send_assignment_to_candidate,
)
from app.store import CandidateRecord
from app.store.factory import get_candidate_store, get_job_repository

router = APIRouter()

# Prefix under which per-candidate artifacts are served (see StaticFiles mount).
MEDIA_PREFIX = "/media/candidates"


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/parse", response_model=ParsedCV)
async def parse(file: UploadFile = File(...)) -> ParsedCV:
    """Accept a PDF upload and return the structured :class:`ParsedCV`.

    Bad input (non-PDF / corrupt / empty) yields a clean 400, not a stack trace.
    """
    data = await file.read()
    filename = file.filename or "upload.pdf"
    try:
        _candidate, parsed = parse_cv_bytes(data, filename=filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return parsed


# --------------------------------------------------------------------------- #
# Jobs (Phase 5 — multi-job)
# --------------------------------------------------------------------------- #
class JobCreateRequest(BaseModel):
    id: str
    title: str
    job_description: str
    rubric: Rubric


@router.get("/jobs", response_model=list[Job])
def list_jobs() -> list[Job]:
    return get_job_repository().list_all()


@router.post("/jobs", response_model=Job, status_code=201)
def create_job(body: JobCreateRequest) -> Job:
    repo = get_job_repository()
    job = Job(
        id=body.id,
        title=body.title,
        job_description=body.job_description,
        rubric=body.rubric,
    )
    try:
        return repo.add(job)
    except ValueError as exc:  # duplicate id
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/jobs/{job_id}", response_model=Job)
def get_job(job_id: str) -> Job:
    job = get_job_repository().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found.")
    return job


@router.post("/jobs/{job_id}/ingest", response_model=IngestionSummary)
def ingest_job(job_id: str) -> IngestionSummary:
    """Run ingestion scoped to a single job: its JD + rubric, its submissions,
    and tag the resulting candidates with ``job_id``."""
    job = get_job_repository().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found.")
    return run_ingestion(job.job_description, job.rubric, job_id=job_id)


def _job_or_404(job_id: str) -> Job:
    job = get_job_repository().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found.")
    return job


def _job_candidates(job_id: str) -> list[CandidateRecord]:
    return [r for r in get_candidate_store().list_all() if r.candidate.job_id == job_id]


@router.get("/jobs/{job_id}/candidates", response_model=list[CandidateRecord])
def list_job_candidates(
    job_id: str,
    tier: Optional[Recommendation] = None,
    status: Optional[CandidateStatus] = None,
) -> list[CandidateRecord]:
    """Candidates for a job, optionally filtered by ``tier`` (recommendation)
    and/or ``status``, ranked by overall score desc."""
    _job_or_404(job_id)
    records = _job_candidates(job_id)
    if tier is not None:
        records = [
            r for r in records if r.evaluation and r.evaluation.recommendation == tier
        ]
    if status is not None:
        records = [r for r in records if r.candidate.status == status]
    return sorted(records, key=lambda r: r.overall_score, reverse=True)


class JobSummary(BaseModel):
    job_id: str
    total: int
    by_tier: dict[str, int]
    by_status: dict[str, int]


@router.get("/jobs/{job_id}/summary", response_model=JobSummary)
def job_summary(job_id: str) -> JobSummary:
    """Counts for a job's candidates, grouped by tier and by status."""
    _job_or_404(job_id)
    records = _job_candidates(job_id)

    by_tier = {t.value: 0 for t in Recommendation}
    by_status = {s.value: 0 for s in CandidateStatus}
    for r in records:
        if r.evaluation is not None:
            by_tier[r.evaluation.recommendation.value] += 1
        by_status[r.candidate.status.value] += 1

    return JobSummary(
        job_id=job_id, total=len(records), by_tier=by_tier, by_status=by_status
    )


# --------------------------------------------------------------------------- #
# Candidates (global list retained; detail joins job context)
# --------------------------------------------------------------------------- #
@router.get("/candidates", response_model=list[CandidateRecord])
def list_candidates() -> list[CandidateRecord]:
    """List all stored candidates (across jobs), highest score first."""
    records = get_candidate_store().list_all()
    return sorted(records, key=lambda r: r.overall_score, reverse=True)


# --------------------------------------------------------------------------- #
# Candidate detail + review decision (Phase 4)
# --------------------------------------------------------------------------- #
class CandidateDetail(BaseModel):
    """Full detail for the review dashboard."""

    candidate: Candidate
    evaluation: Optional[Evaluation] = None
    page_count: int = 0
    text_extraction_quality: Optional[str] = None
    cv_url: Optional[str] = None
    page_image_urls: list[str] = []
    # Job context, joined at read time.
    job_id: Optional[str] = None
    job_title: Optional[str] = None


def _media_url(candidate_id: str, filename: str) -> str:
    return f"{MEDIA_PREFIX}/{candidate_id}/{filename}"


def _to_detail(record: CandidateRecord) -> CandidateDetail:
    cid = record.candidate.id
    cv_url = _media_url(cid, record.cv_file) if record.cv_file else None
    page_urls = [_media_url(cid, name) for name in record.page_image_files]

    job_id = record.candidate.job_id or None
    job_title = None
    if job_id:
        job = get_job_repository().get(job_id)
        job_title = job.title if job else None

    return CandidateDetail(
        candidate=record.candidate,
        evaluation=record.evaluation,
        page_count=record.page_count,
        text_extraction_quality=record.text_extraction_quality,
        cv_url=cv_url,
        page_image_urls=page_urls,
        job_id=job_id,
        job_title=job_title,
    )


@router.get("/candidates/{candidate_id}", response_model=CandidateDetail)
def get_candidate(candidate_id: str) -> CandidateDetail:
    record = get_candidate_store().get(candidate_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Candidate {candidate_id!r} not found.")
    return _to_detail(record)


class DecisionRequest(BaseModel):
    decision: str  # "shortlist" | "reject" (validated in the handler for a clean 400)
    note: Optional[str] = None


@router.patch("/candidates/{candidate_id}/decision", response_model=CandidateDetail)
def decide_candidate(candidate_id: str, body: DecisionRequest) -> CandidateDetail:
    """Record a human shortlist/reject decision — the Phase 4 approval gate.

    Nothing downstream fires yet (that's Phase 5); this only persists the human
    decision (status + note + timestamp).
    """
    store = get_candidate_store()
    try:
        record = store.update_decision(candidate_id, body.decision, body.note)
    except ValueError as exc:  # invalid decision value
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:  # unknown candidate
        raise HTTPException(
            status_code=404, detail=f"Candidate {candidate_id!r} not found."
        ) from exc
    return _to_detail(record)


# --------------------------------------------------------------------------- #
# Assignment dispatch (Phase 5)
# --------------------------------------------------------------------------- #
class SendAssignmentRequest(BaseModel):
    # Resend even when already sent (covers "candidate never got it").
    force: bool = False


@router.post("/candidates/{candidate_id}/send-assignment", response_model=CandidateDetail)
def send_assignment(
    candidate_id: str, body: SendAssignmentRequest | None = None
) -> CandidateDetail:
    """Send the assignment email to a shortlisted candidate — the gated action.

    Guarded so "send" only fires from ``shortlisted`` (or, with ``force``, a
    re-send from ``assignment_sent``). On send failure the status is left
    unchanged and a 502 is returned so the reviewer knows to retry.
    """
    body = body or SendAssignmentRequest()

    # Resolve the sender here (in the routes namespace) and pass it in, so the
    # send flow is centralized in the service while remaining injectable.
    outcome = send_assignment_to_candidate(
        candidate_id, body.force, sender=get_email_sender()
    )

    if outcome.status is SendOutcomeStatus.not_found:
        raise HTTPException(status_code=404, detail=outcome.detail)
    if outcome.status in (
        SendOutcomeStatus.skipped_not_shortlisted,
        SendOutcomeStatus.skipped_already_sent,
    ):
        raise HTTPException(status_code=409, detail=outcome.detail)
    if outcome.status is SendOutcomeStatus.config_error:
        raise HTTPException(status_code=500, detail=outcome.detail)
    if outcome.status is SendOutcomeStatus.failed:
        raise HTTPException(status_code=502, detail=outcome.detail)

    # sent -> return the refreshed detail (same shape as before).
    record = get_candidate_store().get(candidate_id)
    return _to_detail(record)


class BulkSendRequest(BaseModel):
    # None -> all of the job's shortlisted candidates; otherwise exactly these.
    candidate_ids: Optional[list[str]] = None
    force: bool = False


@router.post("/jobs/{job_id}/send-assignments", response_model=BulkSendResult)
def send_assignments(job_id: str, body: BulkSendRequest | None = None) -> BulkSendResult:
    """Bulk-send assignments for a job — Phase 7's "Send to All Shortlisted".

    404 if the job is unknown. Zero eligible candidates is a normal result
    (requested_count 0), not an error. One candidate's failure never aborts the
    batch; outcomes are partitioned into sent/skipped/failed.
    """
    body = body or BulkSendRequest()
    if get_job_repository().get(job_id) is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found.")

    return bulk_send_assignments(
        job_id, body.candidate_ids, body.force, sender=get_email_sender()
    )
