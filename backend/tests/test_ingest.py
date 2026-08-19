"""End-to-end ingestion tests (offline, mock evaluator)."""
from __future__ import annotations

import csv
import shutil
from pathlib import Path

import pytest

from app.config import settings
from app.intake.local_fixture import LocalFixtureIntakeSource
from app.models import CandidateStatus
from app.pipeline import load_default_job_description, load_default_rubric, run_ingestion
from app.store import JSONCandidateStore

SAMPLE_DIR = settings.sample_data_dir


@pytest.fixture
def jd_and_rubric():
    return load_default_job_description(), load_default_rubric()


@pytest.fixture
def store(tmp_path):
    return JSONCandidateStore(path=tmp_path / "candidates.json")


def test_ingestion_processes_three_candidates(store, jd_and_rubric):
    jd, rubric = jd_and_rubric
    # The default fixture has 3 backend-engineer + 2 graphic-designer rows;
    # scope to the backend job to get exactly the 3 originals.
    summary = run_ingestion(
        jd, rubric, job_id="backend-engineer",
        intake_source=LocalFixtureIntakeSource(), store=store,
    )

    assert summary.processed == 3
    assert summary.skipped == 0
    assert summary.failed == 0

    records = store.list_all()
    assert len(records) == 3
    # All scored, tagged with the job, evaluation in range.
    for r in records:
        assert r.candidate.status is CandidateStatus.scored
        assert r.candidate.job_id == "backend-engineer"
        assert r.evaluation is not None
        assert 0 <= r.evaluation.overall_score <= 100
        assert r.evaluation.evaluated_by == "mock"
    assert {r.candidate.email for r in records} == {
        "jane.doe@example.com",
        "john.smith@example.com",
        "sam.rivera@example.com",
    }


def test_second_run_skips_all_via_dedup(store, jd_and_rubric):
    jd, rubric = jd_and_rubric
    first = run_ingestion(
        jd, rubric, job_id="backend-engineer",
        intake_source=LocalFixtureIntakeSource(), store=store,
    )
    assert first.processed == 3

    second = run_ingestion(
        jd, rubric, job_id="backend-engineer",
        intake_source=LocalFixtureIntakeSource(), store=store,
    )
    assert second.processed == 0
    assert second.skipped == 3
    assert second.failed == 0
    # Store still holds exactly 3 (no duplicates).
    assert len(store.list_all()) == 3


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
