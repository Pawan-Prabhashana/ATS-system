"""Store factories.

Always return the JSON stores today. Structured like the intake/evaluator
factories so the Phase 6 Supabase swap is a one-line change here.
"""
from __future__ import annotations

from app.store.base import CandidateRepository, JobRepository
from app.store.job_store import JSONJobRepository
from app.store.json_store import JSONCandidateStore


def get_candidate_store() -> CandidateRepository:
    return JSONCandidateStore()


def get_job_repository() -> JobRepository:
    return JSONJobRepository()
