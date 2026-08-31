"""Re-score already-ingested candidates against their job's CURRENT rubric.

When a job's criteria / weights / description change, existing candidates keep
their old scores until re-scored. This re-runs evaluation on the stored CV (no
re-download of new applicants) and replaces only the evaluation — identity,
status, and human decisions (shortlist/reject + who decided) are preserved.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Callable, Optional

from app.config import get_cv_mode, settings
from app.evaluation import get_evaluator
from app.evaluation.base import Evaluator
from app.models import Evaluation
from app.parsing import parse_cv_bytes
from app.pipeline.ingest import _require_pdf_direct_supported
from app.store.base import CandidateRepository, CandidateRecord
from app.store.factory import get_candidate_store, get_job_repository


def _load_cv_bytes(record: CandidateRecord) -> bytes:
    """The candidate's CV bytes — from Drive (google source) or the local PDF."""
    cand = record.candidate
    if cand.cv_drive_file_id:
        from app.intake.google_forms import GoogleFormsIntakeSource

        return GoogleFormsIntakeSource().download_cv_bytes(cand.cv_drive_file_id)
    if record.artifact_dir and record.cv_file:
        path = settings.data_dir / record.artifact_dir / record.cv_file
        if path.exists():
            return path.read_bytes()
    raise FileNotFoundError("No CV available to rescore (no Drive id or local PDF).")


def rescore_candidate(
    candidate_id: str,
    *,
    store: CandidateRepository | None = None,
    job_repo=None,
    evaluator: Evaluator | None = None,
) -> Evaluation:
    """Re-evaluate one candidate with its job's current rubric; persist + return
    the new evaluation. Status and decision metadata are left untouched."""
    store = store or get_candidate_store()
    job_repo = job_repo or get_job_repository()
    evaluator = evaluator or get_evaluator()
    _require_pdf_direct_supported(evaluator)

    record = store.get(candidate_id)
    if record is None:
        raise KeyError(f"No candidate with id {candidate_id!r}")
    job = job_repo.get(record.candidate.job_id) if record.candidate.job_id else None
    if job is None:
        raise KeyError(f"No job for candidate {candidate_id!r}")

    pdf_direct = get_cv_mode() == "pdf_direct"
    data = _load_cv_bytes(record)
    with tempfile.TemporaryDirectory(prefix="catalist-rescore-") as tmp:
        _cand, parsed = parse_cv_bytes(
            data,
            record.candidate.cv_filename or "cv.pdf",
            candidate_id=candidate_id,
            output_root=Path(tmp),
            render_images=not pdf_direct,
        )
        evaluation = evaluator.evaluate(
            parsed, job.job_description, job.rubric, pdf_bytes=(data if pdf_direct else None)
        )

    # Replace ONLY the evaluation; keep identity, status, decisions, artifacts.
    store.upsert(
        record.candidate,
        parsed,
        evaluation,
        artifact_dir=record.artifact_dir,
        cv_file=record.cv_file,
        page_image_files=record.page_image_files,
    )
    return evaluation


def rescore_job(
    job_id: str,
    *,
    store: CandidateRepository | None = None,
    job_repo=None,
    evaluator: Evaluator | None = None,
    on_progress: "Callable[[int, int], None] | None" = None,
) -> dict:
    """Re-score every candidate in a job. One failure never aborts the batch."""
    store = store or get_candidate_store()
    job_repo = job_repo or get_job_repository()
    evaluator = evaluator or get_evaluator()

    records = store.list_by_job(job_id)
    total = len(records)
    done = ok = failed = 0
    if on_progress:
        on_progress(0, total)
    for rec in records:
        try:
            rescore_candidate(rec.candidate.id, store=store, job_repo=job_repo, evaluator=evaluator)
            ok += 1
        except Exception:  # noqa: BLE001 - keep going across the batch
            failed += 1
        done += 1
        if on_progress:
            on_progress(done, total)
    return {"total": total, "rescored": ok, "failed": failed}
