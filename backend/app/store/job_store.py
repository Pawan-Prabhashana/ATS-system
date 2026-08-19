"""JSON-file job store.

Mirrors :class:`~app.store.json_store.JSONCandidateStore`: a single JSON file,
whole-file read/rewrite, atomic (temp file + ``os.replace``) writes. Placeholder
for the Phase 6 Supabase store; swapping it touches only this file + the factory.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from app.config import get_job_store_path
from app.models import Job

SCHEMA_VERSION = 1


class JSONJobRepository:
    """A ``JobRepository`` backed by one JSON file."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else get_job_store_path()

    def _load(self) -> dict[str, Job]:
        if not self.path.exists():
            return {}
        with self.path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        jobs: dict[str, Job] = {}
        for raw in data.get("jobs", []):
            job = Job.model_validate(raw)
            jobs[job.id] = job
        return jobs

    def add(self, job: Job) -> Job:
        jobs = self._load()
        if job.id in jobs:
            raise ValueError(f"Job id {job.id!r} already exists.")
        jobs[job.id] = job
        self._write(jobs)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        return self._load().get(job_id)

    def list_all(self) -> list[Job]:
        return list(self._load().values())

    def _write(self, jobs: dict[str, Job]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "jobs": [j.model_dump(mode="json") for j in jobs.values()],
        }
        fd, tmp_name = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=".jobs-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, self.path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
            raise
