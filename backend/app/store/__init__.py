"""Candidate + job persistence (JSON stores now; Supabase in Phase 6)."""
from app.store.base import CandidateRecord, CandidateRepository, JobRepository
from app.store.factory import get_candidate_store, get_job_repository
from app.store.job_store import JSONJobRepository
from app.store.json_store import JSONCandidateStore
from app.store.seed import ensure_jobs_seeded, load_seed_jobs, seed_jobs

__all__ = [
    "CandidateRecord",
    "CandidateRepository",
    "JobRepository",
    "get_candidate_store",
    "get_job_repository",
    "JSONCandidateStore",
    "JSONJobRepository",
    "seed_jobs",
    "ensure_jobs_seeded",
    "load_seed_jobs",
]
