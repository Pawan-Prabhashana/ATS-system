"""Ingestion pipeline: intake -> parse -> dedup -> evaluate -> store."""
from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from app.config import get_cv_mode, settings
from app.evaluation import get_evaluator
from app.evaluation.base import Evaluator
from app.evaluation.errors import EvaluatorConfigError
from app.intake.base import IntakeSource, RawSubmission
from app.intake.factory import get_intake_source
from app.intake.local_fixture import LocalFixtureIntakeSource
from app.models import CandidateStatus, Job, ParsedCV, Rubric
from app.parsing import parse_cv_file
from app.store.base import CandidateRepository
from app.store.factory import get_candidate_store

# Stable per-candidate artifact layout (served at /media/candidates/<id>/...).
CANDIDATES_SUBDIR = "candidates"
STORED_CV_NAME = "cv.pdf"


def _scoped_candidate_id(job_id: str, file_hash: str) -> str:
    """Per-(job, CV) candidate id, so the same CV can exist under two jobs
    without colliding in the store (which keys on candidate id)."""
    return hashlib.sha256(f"{job_id}\x00{file_hash}".encode()).hexdigest()[:16]


def _require_pdf_direct_supported(evaluator: Evaluator) -> None:
    """pdf_direct needs Claude's native PDF support. Fail clearly at first use
    (not import) when CV_MODE=pdf_direct but the evaluator isn't anthropic.

    Since Phase 17 pdf_direct is the DEFAULT, so this also fires when CV_MODE is
    simply unset and a non-anthropic evaluator is active — the message names both
    fixes so it's actionable either way."""
    if get_cv_mode() == "pdf_direct" and getattr(evaluator, "name", "") != "anthropic":
        raise EvaluatorConfigError(
            "CV_MODE=pdf_direct (the default) requires EVALUATOR_MODE=anthropic "
            "(Claude's native PDF support); the active evaluator is "
            f"{getattr(evaluator, 'name', '?')!r}. Either set EVALUATOR_MODE=anthropic, "
            "or set CV_MODE=render to use the render (poppler) fallback."
        )


def build_intake_source_for_job(job: Job) -> IntakeSource:
    """Pick the intake source FROM THE JOB, not the global env.

    A job with a ``google_sheet_id`` reads that job's Google Form responses
    Sheet; otherwise it uses the offline local fixtures filtered to this job.
    The Google source is only *constructed* here — no network/credentials are
    touched until ``fetch_new_submissions`` runs.
    """
    if job.google_sheet_id:
        from app.intake.google_forms import GoogleFormsIntakeSource

        return GoogleFormsIntakeSource(sheet_id=job.google_sheet_id)
    return LocalFixtureIntakeSource()


class IngestionFailure(BaseModel):
    submission_ref: str = Field(..., description="cv_file_ref of the failed submission.")
    name: Optional[str] = None
    reason: str


class IngestionSummary(BaseModel):
    processed: int = 0
    skipped: int = 0
    failed: int = 0
    processed_candidate_ids: list[str] = Field(default_factory=list)
    skipped_candidate_ids: list[str] = Field(default_factory=list)
    failures: list[IngestionFailure] = Field(default_factory=list)


def run_ingestion(
    job_description: str,
    rubric: Rubric,
    *,
    job_id: str | None = None,
    intake_source: IntakeSource | None = None,
    store: CandidateRepository | None = None,
    evaluator: Evaluator | None = None,
    work_dir: str | Path | None = None,
) -> IngestionSummary:
    """Ingest submissions for ``job_id`` and return a summary.

    When ``job_id`` is given, intake is filtered to that job and resulting
    candidates are tagged with it (this is how job isolation is enforced). When
    ``None``, all submissions are ingested and candidates are left unassigned.

    Defaults are resolved via the factories (intake/store/evaluator); everything
    is injectable for tests. One bad submission is recorded and skipped — it
    never aborts the batch.
    """
    intake_source = intake_source or get_intake_source()
    store = store or get_candidate_store()
    evaluator = evaluator or get_evaluator()
    _require_pdf_direct_supported(evaluator)

    summary = IngestionSummary()

    submissions = intake_source.fetch_new_submissions(job_id)

    # A working dir for downloaded CVs (parse artifacts go under settings.output_dir).
    tmp_ctx = None
    if work_dir is None:
        tmp_ctx = tempfile.TemporaryDirectory(prefix="catalist-ingest-")
        work_dir = tmp_ctx.name
    work_dir = Path(work_dir)

    try:
        for submission in submissions:
            try:
                _process_one(
                    submission,
                    job_id=job_id,
                    job_description=job_description,
                    rubric=rubric,
                    intake_source=intake_source,
                    store=store,
                    evaluator=evaluator,
                    work_dir=work_dir,
                    summary=summary,
                )
            except Exception as exc:  # noqa: BLE001 - one bad CV must not abort the batch
                summary.failed += 1
                summary.failures.append(
                    IngestionFailure(
                        submission_ref=submission.cv_file_ref,
                        name=submission.name,
                        reason=f"{type(exc).__name__}: {exc}",
                    )
                )
    finally:
        if tmp_ctx is not None:
            tmp_ctx.cleanup()

    return summary


class SiteIngestionSummary(BaseModel):
    """Result of a site-level (all-roles) ingestion run (Phase 15)."""

    processed: int = 0
    processed_by_job: dict[str, int] = Field(default_factory=dict)
    skipped_duplicate: int = 0
    held_total: int = 0
    # Role string -> count. Applicants for a role with no configured job yet —
    # NOT stored/parsed; they stay in the sheet until that job exists. This is
    # what surfaces "you have applicants for a role with no job set up".
    held_by_role: dict[str, int] = Field(default_factory=dict)
    failed: int = 0
    failures: list[IngestionFailure] = Field(default_factory=list)
    processed_candidate_ids: list[str] = Field(default_factory=list)


def run_site_ingestion(
    jobs: list[Job],
    *,
    intake_source: IntakeSource | None = None,
    store: CandidateRepository | None = None,
    evaluator: Evaluator | None = None,
    work_dir: str | Path | None = None,
) -> SiteIngestionSummary:
    """Pull ALL new rows from the single site form and route each to the job
    whose ``role_key`` matches the row's ``role`` EXACTLY (never a fuzzy/AI
    guess). Rows whose role has no configured job are HELD (counted per role, not
    stored or parsed — they remain in the sheet for a later run). One bad row is
    recorded and skipped; it never aborts the batch.
    """
    intake_source = intake_source or get_intake_source()
    store = store or get_candidate_store()
    evaluator = evaluator or get_evaluator()
    _require_pdf_direct_supported(evaluator)

    by_role = {j.role_key: j for j in jobs if j.role_key}
    summary = SiteIngestionSummary()
    submissions = intake_source.fetch_new_submissions()

    tmp_ctx = None
    if work_dir is None:
        tmp_ctx = tempfile.TemporaryDirectory(prefix="catalist-ingest-")
        work_dir = tmp_ctx.name
    work_dir = Path(work_dir)

    try:
        for submission in submissions:
            role = (submission.role or "").strip()
            job = by_role.get(role)
            if job is None:
                key = role or "(no role selected)"
                summary.held_by_role[key] = summary.held_by_role.get(key, 0) + 1
                summary.held_total += 1
                continue
            try:
                outcome, cid = _ingest_one(
                    submission,
                    effective_job_id=job.id,
                    job_description=job.job_description,
                    rubric=job.rubric,
                    intake_source=intake_source,
                    store=store,
                    evaluator=evaluator,
                    work_dir=work_dir,
                )
            except Exception as exc:  # noqa: BLE001 - one bad CV must not abort the batch
                summary.failed += 1
                summary.failures.append(
                    IngestionFailure(
                        submission_ref=submission.cv_file_ref,
                        name=submission.name,
                        reason=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue
            if outcome == "skipped":
                summary.skipped_duplicate += 1
            else:
                summary.processed += 1
                summary.processed_by_job[job.id] = summary.processed_by_job.get(job.id, 0) + 1
                summary.processed_candidate_ids.append(cid)
    finally:
        if tmp_ctx is not None:
            tmp_ctx.cleanup()

    return summary


def _ingest_one(
    submission: RawSubmission,
    *,
    effective_job_id: str,
    job_description: str,
    rubric: Rubric,
    intake_source: IntakeSource,
    store: CandidateRepository,
    evaluator: Evaluator,
    work_dir: Path,
) -> tuple[str, str]:
    """Download → parse → dedup → score → store ONE submission for a KNOWN job.

    Returns ``("skipped", existing_id)`` when this ``(job, CV)`` is already
    stored, else ``("processed", candidate_id)``. Raises on a bad CV — the caller
    records it so one bad row never aborts the batch.
    """
    pdf_direct = get_cv_mode() == "pdf_direct"

    # 1. Download the CV into the (temporary) working dir.
    cv_path = intake_source.download_cv(submission, work_dir)

    # 2. Parse it (raises ValueError on a corrupt/non-PDF file). pdf_direct skips
    #    the poppler render entirely — text + hash only, no page images.
    candidate, parsed_cv = parse_cv_file(cv_path, output_root=work_dir, render_images=not pdf_direct)

    file_hash = candidate.file_hash
    scoped_id = _scoped_candidate_id(effective_job_id, file_hash)

    # 3. Dedup by (job_id, file_hash) — a CV can apply to two openings, but
    #    re-running still skips a job's own duplicates.
    existing = store.get_by_job_and_hash(effective_job_id, file_hash)
    if existing is not None:
        return ("skipped", existing.id)

    # 4. Persist the CV under the scoped id (page_images is empty in pdf_direct,
    #    so no images are written — serverless-friendly).
    artifact_dir, cv_file, page_files = _persist_artifacts(scoped_id, cv_path, parsed_cv)

    # 5. Attach identity + job scoping; adopt the scoped id everywhere. Record the
    #    Drive origin (google source) so the PDF viewer can fetch it on demand.
    cv_drive_file_id = (
        submission.cv_file_ref if getattr(intake_source, "name", "") == "google_forms" else None
    )
    candidate = candidate.model_copy(
        update={
            "id": scoped_id,
            "name": submission.name,
            "email": submission.email,
            "job_id": effective_job_id,
            "cv_drive_file_id": cv_drive_file_id,
            "status": CandidateStatus.parsed,
        }
    )
    parsed_cv = parsed_cv.model_copy(update={"candidate_id": scoped_id})

    # 6. Evaluate, mark scored, persist the record. In pdf_direct the PDF bytes
    #    go straight to Claude (native document block) instead of page images.
    pdf_bytes = cv_path.read_bytes() if pdf_direct else None
    evaluation = evaluator.evaluate(parsed_cv, job_description, rubric, pdf_bytes=pdf_bytes)
    candidate = candidate.model_copy(update={"status": CandidateStatus.scored})
    store.upsert(
        candidate,
        parsed_cv,
        evaluation,
        artifact_dir=artifact_dir,
        cv_file=cv_file,
        page_image_files=page_files,
    )
    return ("processed", scoped_id)


def _process_one(
    submission: RawSubmission,
    *,
    job_id: str | None,
    job_description: str,
    rubric: Rubric,
    intake_source: IntakeSource,
    store: CandidateRepository,
    evaluator: Evaluator,
    work_dir: Path,
    summary: IngestionSummary,
) -> None:
    """Legacy per-job wrapper around :func:`_ingest_one`."""
    effective_job = job_id or submission.job_id or ""
    outcome, cid = _ingest_one(
        submission,
        effective_job_id=effective_job,
        job_description=job_description,
        rubric=rubric,
        intake_source=intake_source,
        store=store,
        evaluator=evaluator,
        work_dir=work_dir,
    )
    if outcome == "skipped":
        summary.skipped += 1
        summary.skipped_candidate_ids.append(cid)
    else:
        summary.processed += 1
        summary.processed_candidate_ids.append(cid)


def _persist_artifacts(
    candidate_id: str,
    cv_path: Path,
    parsed_cv: ParsedCV,
) -> tuple[str, str, list[str]]:
    """Copy the CV and rendered page images into ``data/candidates/<id>/``.

    Returns ``(artifact_dir, cv_file, page_image_files)`` where ``artifact_dir``
    is relative to ``DATA_DIR`` (e.g. ``candidates/<id>``) and the file names are
    normalised (``cv.pdf``, ``page_1.png``, ...) for stable /media URLs.
    """
    rel_dir = f"{CANDIDATES_SUBDIR}/{candidate_id}"
    dest_dir = settings.data_dir / CANDIDATES_SUBDIR / candidate_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Original CV.
    cv_dest = dest_dir / STORED_CV_NAME
    shutil.copyfile(cv_path, cv_dest)

    # Rendered page images, renamed page_1.<ext>, page_2.<ext>, ... in order.
    page_files: list[str] = []
    for page in sorted(parsed_cv.page_images, key=lambda p: p.page_number):
        src = Path(page.image_path)
        if not src.exists():
            continue
        ext = src.suffix or ".png"
        name = f"page_{page.page_number}{ext}"
        shutil.copyfile(src, dest_dir / name)
        page_files.append(name)

    return rel_dir, STORED_CV_NAME, page_files
