"""Shared test helpers."""
from __future__ import annotations

import shutil

from app.config import settings
from app.pipeline.assignment import job_brief_path
from app.store.factory import get_job_repository


def provision_brief(job_id: str, filename: str = "assignment_brief.pdf") -> None:
    """Give an already-stored job an assignment brief (file + filename field).

    Uses the currently-configured job store + data dir (env-isolated per test),
    so a shortlisted candidate in this job can actually be sent an assignment.
    """
    dest = job_brief_path(job_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(settings.sample_data_dir / "assignment_brief.pdf", dest)

    repo = get_job_repository()
    job = repo.get(job_id)
    if job is not None:
        repo.update(job.model_copy(update={"assignment_brief_filename": filename}))
