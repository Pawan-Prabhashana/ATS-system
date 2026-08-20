"""One-time importer: ``python -m app.db.migrate_from_json``.

Reads the existing JSON stores (``data/jobs.json`` and ``data/candidates.json``,
if present) and upserts them into the configured Postgres so the current test
data carries over instead of being lost when you switch STORE_BACKEND=postgres.

Idempotent: a record already present in Postgres (same job id / candidate id,
which is the ``(job_id, file_hash)`` dedup key) is skipped, so re-running is
safe. Requires STORE_BACKEND/DATABASE_URL to point at your Postgres.

NOTE: only the structured records move. The CV PDFs and rendered page images
stay on the local filesystem under ``data/candidates/{id}/`` and are still served
from there — this importer does not touch them.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.db.engine import create_all
from app.store.job_store import JSONJobRepository
from app.store.json_store import JSONCandidateStore
from app.store.sql_candidate_store import SQLCandidateStore
from app.store.sql_job_store import SQLJobRepository


@dataclass
class ImportSummary:
    jobs_imported: int = 0
    jobs_skipped: int = 0
    candidates_imported: int = 0
    candidates_skipped: int = 0


def migrate() -> ImportSummary:
    """Copy jobs + candidates from the JSON files into Postgres. Idempotent."""
    create_all()  # ensure the schema exists before writing

    summary = ImportSummary()

    src_jobs = JSONJobRepository()
    dst_jobs = SQLJobRepository()
    for job in src_jobs.list_all():
        if dst_jobs.get(job.id) is not None:
            summary.jobs_skipped += 1
            continue
        dst_jobs.add(job)
        summary.jobs_imported += 1

    src_cands = JSONCandidateStore()
    dst_cands = SQLCandidateStore()
    for record in src_cands.list_all():
        if dst_cands.get(record.candidate.id) is not None:
            summary.candidates_skipped += 1
            continue
        dst_cands.put_record(record)
        summary.candidates_imported += 1

    return summary


def main() -> None:
    s = migrate()
    print(
        "JSON -> Postgres import complete:\n"
        f"  jobs:       {s.jobs_imported} imported, {s.jobs_skipped} skipped (already present)\n"
        f"  candidates: {s.candidates_imported} imported, {s.candidates_skipped} skipped (already present)"
    )


if __name__ == "__main__":
    main()
