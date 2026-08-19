"""Seed sample jobs from ``sample_data/jobs_seed.json``.

Seed entries are declarative (title, JD, a ``rubric_file`` reference) rather than
hardcoded in app logic — the rubric stays single-sourced in its own JSON file.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.config import settings
from app.models import Job, Rubric
from app.store.base import JobRepository

DEFAULT_SEED_FILE = "jobs_seed.json"


def load_seed_jobs(
    seed_path: str | Path | None = None,
    sample_dir: str | Path | None = None,
) -> list[Job]:
    """Build ``Job`` objects from the seed file (does not persist them)."""
    sample_dir = Path(sample_dir) if sample_dir else settings.sample_data_dir
    seed_path = Path(seed_path) if seed_path else sample_dir / DEFAULT_SEED_FILE

    entries = json.loads(Path(seed_path).read_text(encoding="utf-8"))
    jobs: list[Job] = []
    for entry in entries:
        rubric_file = entry.get("rubric_file")
        rubric = Rubric.model_validate_json((sample_dir / rubric_file).read_text())
        jobs.append(
            Job(
                id=entry["id"],
                title=entry["title"],
                job_description=entry["job_description"],
                rubric=rubric,
                status=entry.get("status", "open"),
            )
        )
    return jobs


def seed_jobs(
    repo: JobRepository,
    seed_path: str | Path | None = None,
    sample_dir: str | Path | None = None,
) -> list[Job]:
    """Add any seed jobs not already present in ``repo``; return those added."""
    existing = {j.id for j in repo.list_all()}
    added: list[Job] = []
    for job in load_seed_jobs(seed_path, sample_dir):
        if job.id not in existing:
            repo.add(job)
            added.append(job)
    return added


def ensure_jobs_seeded(repo: JobRepository) -> list[Job]:
    """Seed jobs only if the repository is currently empty (startup convenience)."""
    if repo.list_all():
        return []
    try:
        return seed_jobs(repo)
    except FileNotFoundError:
        return []
