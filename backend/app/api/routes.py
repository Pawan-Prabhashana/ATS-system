"""FastAPI routes: parsing core (Phase 1) + ingestion/listing/review (Phase 3-4)."""
from __future__ import annotations

import re
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ValidationError

from app.email.factory import get_email_sender
from app.models import (
    Candidate,
    CandidateStatus,
    Evaluation,
    Job,
    JobStatus,
    ParsedCV,
    Recommendation,
    Rubric,
)
from app.parsing import parse_cv_bytes
from app.pipeline import (
    IngestionSummary,
    build_intake_source_for_job,
    run_ingestion,
)
from app.pipeline.assignment import (
    BRIEF_FILENAME,
    BulkSendResult,
    SendOutcomeStatus,
    bulk_send_assignments,
    job_brief_path,
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
# Jobs (Phase 5 multi-job; Phase 7 config-as-data)
# --------------------------------------------------------------------------- #
class JobCreateRequest(BaseModel):
    """Create a job. ``id`` is auto-generated as a slug from ``title``."""

    title: str
    job_description: str
    rubric: dict  # validated -> clean 400 (see _validated_rubric)
    google_sheet_id: Optional[str] = None
    status: Optional[JobStatus] = None


class JobUpdateRequest(BaseModel):
    """PATCH a job — every field optional; only provided fields change."""

    title: Optional[str] = None
    job_description: Optional[str] = None
    rubric: Optional[dict] = None
    google_sheet_id: Optional[str] = None
    status: Optional[JobStatus] = None
    assignment_deadline_days: Optional[int] = None
    assignment_message: Optional[str] = None


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "job"


def _unique_job_id(repo, base: str) -> str:
    if repo.get(base) is None:
        return base
    n = 2
    while repo.get(f"{base}-{n}") is not None:
        n += 1
    return f"{base}-{n}"


def _validated_rubric(raw: dict) -> Rubric:
    """Validate a rubric payload; a bad one is a clean 400, not a 422/500."""
    try:
        return Rubric.model_validate(raw)
    except ValidationError as exc:
        msgs = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        raise HTTPException(status_code=400, detail=f"Invalid rubric: {msgs}") from exc


@router.get("/jobs", response_model=list[Job])
def list_jobs() -> list[Job]:
    return get_job_repository().list_all()


@router.post("/jobs", response_model=Job, status_code=201)
def create_job(body: JobCreateRequest) -> Job:
    repo = get_job_repository()
    rubric = _validated_rubric(body.rubric)
    job = Job(
        id=_unique_job_id(repo, _slugify(body.title)),
        title=body.title,
        job_description=body.job_description,
        rubric=rubric,
        google_sheet_id=body.google_sheet_id,
        status=body.status or JobStatus.open,
    )
    return repo.add(job)


@router.get("/jobs/{job_id}", response_model=Job)
def get_job(job_id: str) -> Job:
    job = get_job_repository().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found.")
    return job


@router.patch("/jobs/{job_id}", response_model=Job)
def update_job(job_id: str, body: JobUpdateRequest) -> Job:
    repo = get_job_repository()
    job = repo.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found.")

    updates: dict = {}
    if body.title is not None:
        updates["title"] = body.title
    if body.job_description is not None:
        updates["job_description"] = body.job_description
    if body.rubric is not None:
        updates["rubric"] = _validated_rubric(body.rubric)
    if body.google_sheet_id is not None:
        updates["google_sheet_id"] = body.google_sheet_id
    if body.status is not None:
        updates["status"] = body.status
    if body.assignment_deadline_days is not None:
        updates["assignment_deadline_days"] = body.assignment_deadline_days
    if body.assignment_message is not None:
        updates["assignment_message"] = body.assignment_message
    return repo.update(job.model_copy(update=updates))


@router.post("/jobs/{job_id}/close", response_model=Job)
def close_job(job_id: str) -> Job:
    """Soft-close a job (status=closed) — preserves candidate integrity."""
    repo = get_job_repository()
    job = repo.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found.")
    return repo.update(job.model_copy(update={"status": JobStatus.closed}))


@router.post("/jobs/{job_id}/ingest", response_model=IngestionSummary)
def ingest_job(job_id: str) -> IngestionSummary:
    """Run ingestion scoped to a single job, selecting the intake source FROM
    THE JOB (its Google Sheet if connected, else local fixtures)."""
    job = get_job_repository().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found.")
    source = build_intake_source_for_job(job)
    return run_ingestion(
        job.job_description, job.rubric, job_id=job_id, intake_source=source
    )


class IntakeProbeResult(BaseModel):
    connected: bool
    row_count: int = 0
    detected_columns: dict[str, Optional[str]] = {}
    error: Optional[str] = None


class TestIntakeRequest(BaseModel):
    """Optional override so the settings form can test a Sheet ID before save."""

    google_sheet_id: Optional[str] = None


@router.post("/jobs/{job_id}/test-intake", response_model=IntakeProbeResult)
def test_intake(
    job_id: str, body: TestIntakeRequest | None = None
) -> IntakeProbeResult:
    """Operability check: try to read the job's Google Sheet header + row count.

    Never raises to a 500 — any Google/credentials error is reported as
    ``connected: false`` with a human-readable ``error``.
    """
    job = get_job_repository().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found.")

    typed = (body.google_sheet_id or "").strip() if body else ""
    sheet_id = typed or job.google_sheet_id
    if not sheet_id:
        return IntakeProbeResult(
            connected=False,
            error="No Google Sheet connected for this job.",
        )

    from app.intake.google_forms import GoogleFormsIntakeSource

    source = GoogleFormsIntakeSource(sheet_id=sheet_id)
    return IntakeProbeResult(**source.probe())


# --------------------------------------------------------------------------- #
# Per-job assignment brief (Phase 9)
# --------------------------------------------------------------------------- #
@router.post("/jobs/{job_id}/assignment-brief", response_model=Job)
async def upload_assignment_brief(
    job_id: str, file: UploadFile = File(...)
) -> Job:
    """Upload the PDF the candidates will receive. Non-PDF → clean 400."""
    repo = get_job_repository()
    job = repo.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found.")

    data = await file.read()
    if b"%PDF-" not in data[:1024]:
        raise HTTPException(
            status_code=400, detail="The assignment brief must be a PDF file."
        )

    path = job_brief_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    filename = file.filename or BRIEF_FILENAME
    return repo.update(job.model_copy(update={"assignment_brief_filename": filename}))


@router.get("/jobs/{job_id}/assignment-brief")
def get_assignment_brief(job_id: str):
    """Serve the job's brief PDF for preview/confirm. 404 if none uploaded."""
    job = get_job_repository().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found.")
    path = job_brief_path(job_id)
    if not (job.assignment_brief_filename and path.exists()):
        raise HTTPException(
            status_code=404, detail="No assignment brief uploaded for this job."
        )
    return FileResponse(
        str(path),
        media_type="application/pdf",
        filename=job.assignment_brief_filename,
    )


@router.delete("/jobs/{job_id}/assignment-brief", response_model=Job)
def delete_assignment_brief(job_id: str) -> Job:
    repo = get_job_repository()
    job = repo.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found.")
    path = job_brief_path(job_id)
    if path.exists():
        path.unlink()
    return repo.update(job.model_copy(update={"assignment_brief_filename": None}))


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
        SendOutcomeStatus.no_assignment_brief,
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
