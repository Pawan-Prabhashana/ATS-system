"""Kick long-running pipeline work (pull, rescore) onto a background thread and
report progress via ``app.pipeline.progress`` so the UI can poll + show "X of Y".

Single-instance, in-process (see progress.py for the Render-Free caveat). Each
key runs at most one job at a time; a second start returns the in-flight snapshot.
"""
from __future__ import annotations

import threading

from app.pipeline import run_site_ingestion
from app.pipeline.progress import finish, report, snapshot, try_start
from app.pipeline.rescore import rescore_job
from app.store.factory import get_job_repository

INGEST_KEY = "site-ingest"


def _spawn(target) -> None:
    threading.Thread(target=target, daemon=True).start()


def start_site_ingestion() -> dict:
    """Start (or return the in-progress) background pull of the site form."""
    if not try_start(INGEST_KEY, "ingest"):
        return snapshot(INGEST_KEY) or {"status": "running"}

    def run() -> None:
        try:
            jobs = get_job_repository().list_all()
            summary = run_site_ingestion(
                jobs, on_progress=lambda d, t: report(INGEST_KEY, d, t)
            )
            finish(INGEST_KEY, summary=summary.model_dump())
        except Exception as exc:  # noqa: BLE001
            finish(INGEST_KEY, error=f"{type(exc).__name__}: {exc}")

    _spawn(run)
    return snapshot(INGEST_KEY) or {"status": "running"}


def ingestion_progress() -> dict:
    return snapshot(INGEST_KEY) or {"status": "idle"}


def job_ingest_key(job_id: str) -> str:
    return f"ingest:job:{job_id}"


def start_job_ingestion(job_id: str) -> dict:
    """Start (or return the in-progress) background pull for ONE job — only the
    applicants who picked that job's role are downloaded + scored."""
    key = job_ingest_key(job_id)
    if not try_start(key, "ingest"):
        return snapshot(key) or {"status": "running"}

    def run() -> None:
        try:
            job = get_job_repository().get(job_id)
            if job is None:
                finish(key, error=f"Job {job_id!r} not found.")
                return
            summary = run_site_ingestion(
                [job],
                restrict_role=job.role_key,
                on_progress=lambda d, t: report(key, d, t),
            )
            finish(key, summary=summary.model_dump())
        except Exception as exc:  # noqa: BLE001
            finish(key, error=f"{type(exc).__name__}: {exc}")

    _spawn(run)
    return snapshot(key) or {"status": "running"}


def job_ingestion_progress(job_id: str) -> dict:
    return snapshot(job_ingest_key(job_id)) or {"status": "idle"}


def rescore_key(job_id: str) -> str:
    return f"rescore:{job_id}"


def start_job_rescore(job_id: str) -> dict:
    """Start (or return the in-progress) background rescore of a job."""
    key = rescore_key(job_id)
    if not try_start(key, "rescore"):
        return snapshot(key) or {"status": "running"}

    def run() -> None:
        try:
            summary = rescore_job(job_id, on_progress=lambda d, t: report(key, d, t))
            finish(key, summary=summary)
        except Exception as exc:  # noqa: BLE001
            finish(key, error=f"{type(exc).__name__}: {exc}")

    _spawn(run)
    return snapshot(key) or {"status": "running"}


def rescore_progress(job_id: str) -> dict:
    return snapshot(rescore_key(job_id)) or {"status": "idle"}
