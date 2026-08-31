"""FastAPI routes: parsing core (Phase 1) + ingestion/listing/review (Phase 3-4)."""
from __future__ import annotations

import io
import re
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from app.auth import current_user
from pydantic import BaseModel, ValidationError

from app.config import settings
from app.email.factory import get_email_sender
from app.evaluation.errors import EvaluatorConfigError
from app.intake.errors import IntakeError
from app.intake.factory import get_intake_source
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
    SiteIngestionSummary,
    run_site_ingestion,
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
    """Create a job. ``id`` is auto-generated as a slug from ``title``.

    ``role_key`` is the EXACT form dropdown value this job serves (Phase 15);
    unique across jobs. There is no per-job Sheet ID any more — the form is
    site-level and rows route by role.
    """

    title: str
    job_description: str
    rubric: dict  # validated -> clean 400 (see _validated_rubric)
    role_key: str
    status: Optional[JobStatus] = None


class JobUpdateRequest(BaseModel):
    """PATCH a job — every field optional; only provided fields change."""

    title: Optional[str] = None
    job_description: Optional[str] = None
    rubric: Optional[dict] = None
    role_key: Optional[str] = None
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


def _check_role_key_unique(repo, role_key: str, *, exclude_id: str | None = None) -> None:
    """Reject a role_key already used by another job (exact match) — a 400."""
    key = (role_key or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="role_key is required and cannot be empty.")
    for j in repo.list_all():
        if j.id != exclude_id and (j.role_key or "").strip() == key:
            raise HTTPException(
                status_code=400,
                detail=f"role_key {key!r} is already used by job {j.id!r}. Each job serves a distinct role.",
            )


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
    _check_role_key_unique(repo, body.role_key)
    job = Job(
        id=_unique_job_id(repo, _slugify(body.title)),
        title=body.title,
        role_key=body.role_key.strip(),
        job_description=body.job_description,
        rubric=rubric,
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
    if body.role_key is not None:
        _check_role_key_unique(repo, body.role_key, exclude_id=job_id)
        updates["role_key"] = body.role_key.strip()
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


# --------------------------------------------------------------------------- #
# Site-level intake (Phase 15): ONE form, routed to jobs by role_key
# --------------------------------------------------------------------------- #
@router.post("/ingest", response_model=SiteIngestionSummary)
def site_ingest() -> SiteIngestionSummary:
    """Pull ALL new applicants from the single site form and route each row to
    the job whose ``role_key`` matches the row's role EXACTLY. Rows for a role
    with no configured job are HELD (reported per role), not stored."""
    jobs = get_job_repository().list_all()
    try:
        return run_site_ingestion(jobs)
    except EvaluatorConfigError as exc:
        # e.g. CV_MODE=pdf_direct without EVALUATOR_MODE=anthropic — a clean 400,
        # never a raw 500.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except IntakeError as exc:
        # Reading the site sheet failed (API disabled / not shared / no sheet).
        raise HTTPException(
            status_code=502, detail=f"Couldn't read the application form: {exc}"
        ) from exc


class RoleInfo(BaseModel):
    role: str
    applicant_count: int = 0
    has_job: bool = False
    job_id: Optional[str] = None
    job_title: Optional[str] = None


@router.get("/roles", response_model=list[RoleInfo])
def list_roles() -> list[RoleInfo]:
    """Every role seen on the form + every configured job, merged.

    For each distinct role value: its applicant count and whether a job exists
    (``has_job`` + ``job_id``). Configured jobs with zero applicants are included
    too, so the admin sees the full picture — this powers "roles needing setup".
    """
    jobs = get_job_repository().list_all()
    by_role_key: dict[str, object] = {(j.role_key or "").strip(): j for j in jobs if (j.role_key or "").strip()}

    # Count applicants per role from the site form (resilient — an unreadable
    # sheet just means zero counts; /intake/status reports the read problem).
    counts: dict[str, int] = {}
    try:
        for sub in get_intake_source().fetch_new_submissions():
            role = (sub.role or "").strip()
            if role:
                counts[role] = counts.get(role, 0) + 1
    except IntakeError:
        counts = {}

    roles = set(counts) | set(by_role_key)
    out: list[RoleInfo] = []
    for role in sorted(roles):
        job = by_role_key.get(role)
        out.append(
            RoleInfo(
                role=role,
                applicant_count=counts.get(role, 0),
                has_job=job is not None,
                job_id=getattr(job, "id", None),
                job_title=getattr(job, "title", None),
            )
        )
    return out


class IntakeStatus(BaseModel):
    connected: bool
    row_count: int = 0
    role_column_detected: bool = False
    detected_columns: dict[str, Optional[str]] = {}
    distinct_roles: list[str] = []
    error: Optional[str] = None


def _intake_status() -> IntakeStatus:
    """Can we read the single site form, and is the role column detected? Never
    raises to a 500."""
    source = get_intake_source()
    probe = getattr(source, "probe", None)
    if probe is None:  # pragma: no cover - all current sources implement probe
        return IntakeStatus(connected=False, error="Intake source has no status probe.")
    try:
        return IntakeStatus(**probe())
    except Exception as exc:  # noqa: BLE001 - report, never 500
        return IntakeStatus(connected=False, error=str(exc))


@router.post("/intake/status", response_model=IntakeStatus)
def intake_status_post() -> IntakeStatus:
    return _intake_status()


@router.get("/intake/status", response_model=IntakeStatus)
def intake_status_get() -> IntakeStatus:
    return _intake_status()


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
    # Auth-protected PDF stream (Phase 16). Present when a PDF is retrievable
    # (Drive origin or a persisted local PDF). The frontend embeds this when
    # there are no page images (pdf_direct mode).
    cv_pdf_url: Optional[str] = None
    # Job context, joined at read time.
    job_id: Optional[str] = None
    job_title: Optional[str] = None


def _media_url(candidate_id: str, filename: str) -> str:
    return f"{MEDIA_PREFIX}/{candidate_id}/{filename}"


def _local_cv_path(record: CandidateRecord):
    """Filesystem path to the persisted CV PDF, or None if not on disk."""
    if not record.cv_file or not record.artifact_dir:
        return None
    path = settings.data_dir / record.artifact_dir / record.cv_file
    return path if path.exists() else None


def _to_detail(record: CandidateRecord) -> CandidateDetail:
    cid = record.candidate.id
    cv_url = _media_url(cid, record.cv_file) if record.cv_file else None
    page_urls = [_media_url(cid, name) for name in record.page_image_files]

    # A PDF is retrievable if it came from Drive or a local copy exists.
    has_pdf = bool(record.candidate.cv_drive_file_id) or _local_cv_path(record) is not None
    cv_pdf_url = f"/candidates/{cid}/cv" if has_pdf else None

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
        cv_pdf_url=cv_pdf_url,
        job_id=job_id,
        job_title=job_title,
    )


@router.get("/candidates/{candidate_id}", response_model=CandidateDetail)
def get_candidate(candidate_id: str) -> CandidateDetail:
    record = get_candidate_store().get(candidate_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Candidate {candidate_id!r} not found.")
    return _to_detail(record)


@router.get("/candidates/{candidate_id}/cv")
def get_candidate_cv(candidate_id: str):
    """Stream the CV PDF inline (auth-protected — CVs sit behind login).

    Drive origin -> fetch the bytes via the service account, in memory (no disk,
    serverless-safe); else the persisted local PDF; else 404."""
    record = get_candidate_store().get(candidate_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Candidate {candidate_id!r} not found.")
    filename = record.candidate.cv_filename or "cv.pdf"

    drive_id = record.candidate.cv_drive_file_id
    if drive_id:
        from app.intake.google_forms import GoogleFormsIntakeSource

        try:
            data = GoogleFormsIntakeSource().download_cv_bytes(drive_id)
        except IntakeError as exc:
            raise HTTPException(status_code=502, detail=f"Couldn't fetch the CV from Drive: {exc}") from exc
        return StreamingResponse(
            io.BytesIO(data),
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )

    local = _local_cv_path(record)
    if local is not None:
        return FileResponse(local, media_type="application/pdf", filename=filename)

    raise HTTPException(status_code=404, detail="No CV file available for this candidate.")


class DecisionRequest(BaseModel):
    decision: str  # "shortlist" | "reject" (validated in the handler for a clean 400)
    note: Optional[str] = None


@router.patch("/candidates/{candidate_id}/decision", response_model=CandidateDetail)
def decide_candidate(
    candidate_id: str, body: DecisionRequest, actor: dict = Depends(current_user)
) -> CandidateDetail:
    """Record a human shortlist/reject decision — the Phase 4 approval gate.

    Persists the decision (status + note + timestamp) and WHO made it, so the UI
    can show "Shortlisted by <name>".
    """
    store = get_candidate_store()
    try:
        record = store.update_decision(
            candidate_id, body.decision, body.note, decided_by=actor.get("full_name")
        )
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
    # Submission deadline shown in the email, chosen at send time.
    deadline: Optional[date] = None


@router.post("/candidates/{candidate_id}/send-assignment", response_model=CandidateDetail)
def send_assignment(
    candidate_id: str,
    body: SendAssignmentRequest | None = None,
    actor: dict = Depends(current_user),
) -> CandidateDetail:
    """Send the assignment email to a shortlisted candidate — the gated action.

    Guarded so "send" only fires from ``shortlisted`` (or, with ``force``, a
    re-send from ``assignment_sent``). The email is signed with the sender's full
    name and records who sent it. On send failure the status is left unchanged
    and a 502 is returned so the reviewer knows to retry.
    """
    body = body or SendAssignmentRequest()

    # Resolve the sender here (in the routes namespace) and pass it in, so the
    # send flow is centralized in the service while remaining injectable.
    outcome = send_assignment_to_candidate(
        candidate_id,
        body.force,
        sender=get_email_sender(),
        sender_name=actor.get("full_name"),
        deadline_date=body.deadline,
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
    # Submission deadline shown in the emails, chosen at send time.
    deadline: Optional[date] = None


@router.post("/jobs/{job_id}/send-assignments", response_model=BulkSendResult)
def send_assignments(
    job_id: str,
    body: BulkSendRequest | None = None,
    actor: dict = Depends(current_user),
) -> BulkSendResult:
    """Bulk-send assignments for a job — Phase 7's "Send to All Shortlisted".

    404 if the job is unknown. Zero eligible candidates is a normal result
    (requested_count 0), not an error. One candidate's failure never aborts the
    batch; outcomes are partitioned into sent/skipped/failed.
    """
    body = body or BulkSendRequest()
    if get_job_repository().get(job_id) is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found.")

    return bulk_send_assignments(
        job_id,
        body.candidate_ids,
        body.force,
        sender=get_email_sender(),
        sender_name=actor.get("full_name"),
        deadline_date=body.deadline,
    )
