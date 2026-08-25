"""End-to-end ingestion tests (offline, mock evaluator)."""
from __future__ import annotations

import csv
import shutil
from pathlib import Path

import pytest

from app.config import settings
from app.intake.local_fixture import LocalFixtureIntakeSource
from app.models import CandidateStatus, Job, Rubric
from app.pipeline import (
    load_default_job_description,
    load_default_rubric,
    run_ingestion,
    run_site_ingestion,
)
from app.store import JSONCandidateStore

SAMPLE_DIR = settings.sample_data_dir


@pytest.fixture
def jd_and_rubric():
    return load_default_job_description(), load_default_rubric()


@pytest.fixture
def store(tmp_path):
    return JSONCandidateStore(path=tmp_path / "candidates.json")


def _jobs(jd, rubric):
    return [
        Job(id="backend-engineer", title="Backend Engineer", role_key="Backend Engineer", job_description=jd, rubric=rubric),
        Job(id="graphic-designer", title="Graphic Designer", role_key="Graphic Design Intern", job_description=jd, rubric=rubric),
    ]


def test_site_ingestion_routes_by_role(store, jd_and_rubric):
    jd, rubric = jd_and_rubric
    summary = run_site_ingestion(_jobs(jd, rubric), intake_source=LocalFixtureIntakeSource(), store=store)

    # Backend Engineer x3 + Graphic Design Intern x1 routed; Motion Designer held.
    assert summary.processed_by_job == {"backend-engineer": 3, "graphic-designer": 1}
    assert summary.held_by_role == {"Motion Designer": 1}
    assert summary.failed == 0

    records = store.list_all()
    assert len(records) == 4  # held Motion Designer NOT stored
    for r in records:
        assert r.candidate.status is CandidateStatus.scored
        assert r.evaluation is not None
        assert 0 <= r.evaluation.overall_score <= 100
        assert r.evaluation.evaluated_by == "mock"
    backend = {r.candidate.email for r in records if r.candidate.job_id == "backend-engineer"}
    assert backend == {"jane.doe@example.com", "john.smith@example.com", "sam.rivera@example.com"}


def test_second_run_skips_all_via_dedup(store, jd_and_rubric):
    jd, rubric = jd_and_rubric
    first = run_site_ingestion(_jobs(jd, rubric), intake_source=LocalFixtureIntakeSource(), store=store)
    assert first.processed == 4

    second = run_site_ingestion(_jobs(jd, rubric), intake_source=LocalFixtureIntakeSource(), store=store)
    assert second.processed == 0
    assert second.skipped_duplicate == 4
    assert second.failed == 0
    assert len(store.list_all()) == 4


def test_one_corrupt_cv_does_not_abort_batch(tmp_path, store, jd_and_rubric):
    jd, rubric = jd_and_rubric

    # Build an isolated fixture dir: 2 valid CVs + 1 corrupt file.
    base = tmp_path / "cvs"
    base.mkdir()
    shutil.copyfile(SAMPLE_DIR / "sample_cv_text.pdf", base / "good1.pdf")
    shutil.copyfile(SAMPLE_DIR / "sample_cv_text_2.pdf", base / "good2.pdf")
    (base / "broken.pdf").write_bytes(b"this is not a real pdf file")

    csv_path = tmp_path / "responses.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["timestamp", "name", "email", "cv_filename"])
        w.writerow(["2026-08-10 09:00:00", "Good One", "g1@example.com", "good1.pdf"])
        w.writerow(["2026-08-10 09:05:00", "Broken", "bad@example.com", "broken.pdf"])
        w.writerow(["2026-08-10 09:10:00", "Good Two", "g2@example.com", "good2.pdf"])

    source = LocalFixtureIntakeSource(csv_path=csv_path, base_dir=base)
    summary = run_ingestion(jd, rubric, intake_source=source, store=store)

    assert summary.processed == 2
    assert summary.failed == 1
    assert len(summary.failures) == 1
    assert summary.failures[0].submission_ref == "broken.pdf"
    assert summary.failures[0].reason  # non-empty reason
    # The two good candidates made it into the store.
    assert len(store.list_all()) == 2


def test_missing_cv_file_recorded_as_failure(tmp_path, store, jd_and_rubric):
    jd, rubric = jd_and_rubric
    csv_path = tmp_path / "responses.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["timestamp", "name", "email", "cv_filename"])
        w.writerow(["2026-08-10 09:00:00", "Ghost", "ghost@example.com", "nope.pdf"])

    source = LocalFixtureIntakeSource(csv_path=csv_path, base_dir=tmp_path)
    summary = run_ingestion(jd, rubric, intake_source=source, store=store)
    assert summary.processed == 0
    assert summary.failed == 1
