"""Command-line entry point.

Usage:
    python -m app.cli <path-to-pdf> [--rubric rubric.json] [--jd job_description.txt]
        Parse a single CV, run the configured evaluator, print ParsedCV + Evaluation.

    python -m app.cli seed-jobs
        Seed the sample jobs from sample_data/jobs_seed.json.

    python -m app.cli ingest <job_id>
        Ingest that job's submissions (its JD + rubric), print the
        IngestionSummary, then list the job's candidates ranked by score.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.config import settings
from app.evaluation import EvaluatorError, get_evaluator
from app.models import Rubric
from app.parsing import parse_cv_file

DEFAULT_RUBRIC = settings.sample_data_dir / "rubric.json"
DEFAULT_JD = settings.sample_data_dir / "job_description.txt"


def _load_rubric(path: Path) -> Rubric:
    if path.exists():
        return Rubric.model_validate_json(path.read_text())
    # Minimal fallback so the CLI works even without sample data.
    return Rubric(
        job_title="Unspecified role",
        criteria=[
            {"name": "Relevant experience", "description": "", "weight": 1.0},
            {"name": "Skills match", "description": "", "weight": 1.0},
        ],
    )


def _load_jd(path: Path) -> str:
    return path.read_text() if path.exists() else "No job description provided."


# --------------------------------------------------------------------------- #
# parse (default) subcommand
# --------------------------------------------------------------------------- #
def _run_parse(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="app.cli", description="Parse a CV and evaluate it."
    )
    parser.add_argument("pdf", help="Path to the CV PDF.")
    parser.add_argument("--rubric", default=str(DEFAULT_RUBRIC), help="Path to rubric JSON.")
    parser.add_argument("--jd", default=str(DEFAULT_JD), help="Path to job-description text.")
    args = parser.parse_args(argv)

    try:
        _candidate, parsed = parse_cv_file(args.pdf)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    rubric = _load_rubric(Path(args.rubric))
    job_description = _load_jd(Path(args.jd))

    try:
        evaluation = get_evaluator().evaluate(parsed, job_description, rubric)
    except EvaluatorError as exc:
        print(f"error: evaluation failed: {exc}", file=sys.stderr)
        return 2

    output = {
        "parsed_cv": parsed.model_dump(mode="json"),
        "evaluation": evaluation.model_dump(mode="json"),
    }
    print(json.dumps(output, indent=2))
    return 0


# --------------------------------------------------------------------------- #
# seed-jobs subcommand
# --------------------------------------------------------------------------- #
def _run_seed_jobs(argv: list[str]) -> int:
    from app.store import get_job_repository, seed_jobs

    parser = argparse.ArgumentParser(
        prog="app.cli seed-jobs",
        description="Seed sample jobs from sample_data/jobs_seed.json.",
    )
    parser.parse_args(argv)

    added = seed_jobs(get_job_repository())
    if added:
        print(f"Seeded {len(added)} job(s):")
        for job in added:
            print(f"  - {job.id}: {job.title}")
    else:
        print("No new jobs to seed (all seed jobs already present).")
    return 0


# --------------------------------------------------------------------------- #
# ingest subcommand (job-scoped)
# --------------------------------------------------------------------------- #
def _run_ingest(argv: list[str]) -> int:
    from app.pipeline import run_ingestion
    from app.store import get_candidate_store, get_job_repository

    parser = argparse.ArgumentParser(
        prog="app.cli ingest", description="Ingest submissions for a job."
    )
    parser.add_argument("job_id", help="Job id to ingest (see `seed-jobs` / GET /jobs).")
    args = parser.parse_args(argv)

    job = get_job_repository().get(args.job_id)
    if job is None:
        jobs = get_job_repository().list_all()
        known = ", ".join(j.id for j in jobs) or "(none — run `seed-jobs` first)"
        print(f"error: job {args.job_id!r} not found. Known jobs: {known}", file=sys.stderr)
        return 1

    try:
        summary = run_ingestion(job.job_description, job.rubric, job_id=job.id)
    except EvaluatorError as exc:
        print(f"error: evaluation failed: {exc}", file=sys.stderr)
        return 2

    print(f"=== Ingestion summary for job '{job.id}' ({job.title}) ===")
    print(json.dumps(summary.model_dump(mode="json"), indent=2))

    records = [
        r for r in get_candidate_store().list_all() if r.candidate.job_id == job.id
    ]
    records.sort(key=lambda r: r.overall_score, reverse=True)
    print(f"\n=== Candidates for '{job.id}' (ranked by score) ===")
    for rank, record in enumerate(records, start=1):
        c = record.candidate
        score = record.evaluation.overall_score if record.evaluation else None
        rec = record.evaluation.recommendation.value if record.evaluation else "-"
        print(
            f"{rank}. {c.name or '(unknown)'} <{c.email or '-'}> "
            f"score={score} rec={rec} status={c.status.value} id={c.id}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "ingest":
        return _run_ingest(argv[1:])
    if argv and argv[0] == "seed-jobs":
        return _run_seed_jobs(argv[1:])
    return _run_parse(argv)


if __name__ == "__main__":
    raise SystemExit(main())
