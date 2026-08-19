"""Phase 7A: job config as first-class data + per-job ingest routing (offline)."""
from __future__ import annotations

import csv
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.intake.google_forms import GoogleFormsIntakeSource
from app.intake.local_fixture import LocalFixtureIntakeSource
from app.main import app
from app.models import Job, JobStatus, Rubric
from app.pipeline import build_intake_source_for_job, run_ingestion
from app.store import JSONCandidateStore, JSONJobRepository

client = TestClient(app)

SAMPLE_DIR = settings.sample_data_dir


def _rubric_payload() -> dict:
    return {"job_title": "X", "criteria": [{"name": "c", "weight": 1.0}]}


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("CATALIST_JOB_STORE_PATH", str(tmp_path / "jobs.json"))
    monkeypatch.setenv("CATALIST_CANDIDATE_STORE_PATH", str(tmp_path / "candidates.json"))


def _create(title="Senior Backend Engineer", **extra) -> dict:
    body = {"title": title, "job_description": "jd", "rubric": _rubric_payload(), **extra}
    resp = client.post("/jobs", json=body)
    return resp


# --------------------------------------------------------------------------- #
# Create: auto-slug, collision, validation
# --------------------------------------------------------------------------- #
def test_create_auto_slugs_id(api):
    resp = _create("Senior Backend Engineer!")
    assert resp.status_code == 201
    assert resp.json()["id"] == "senior-backend-engineer"
    assert resp.json()["google_sheet_id"] is None


def test_create_collision_suffixing(api):
    assert _create("Designer").json()["id"] == "designer"
    assert _create("Designer").json()["id"] == "designer-2"
    assert _create("Designer").json()["id"] == "designer-3"


def test_create_with_sheet_id_and_status(api):
    resp = _create("Data Eng", google_sheet_id="SHEET123", status="closed")
    assert resp.status_code == 201
    body = resp.json()
    assert body["google_sheet_id"] == "SHEET123"
    assert body["status"] == "closed"


@pytest.mark.parametrize(
    "bad_rubric",
    [
        {"job_title": "X", "criteria": []},  # no criteria
        {"job_title": "X", "criteria": [{"name": "c", "weight": 0}]},  # weight not > 0
        {"job_title": "X", "criteria": [{"name": "c", "weight": -1}]},
    ],
)
def test_create_rejects_invalid_rubric_400(api, bad_rubric):
    resp = client.post(
        "/jobs", json={"title": "T", "job_description": "jd", "rubric": bad_rubric}
    )
    assert resp.status_code == 400
    assert "rubric" in resp.json()["detail"].lower()


# --------------------------------------------------------------------------- #
# PATCH + close
# --------------------------------------------------------------------------- #
def test_patch_updates_each_field(api):
    jid = _create("Role").json()["id"]

    resp = client.patch(
        f"/jobs/{jid}",
        json={
            "title": "Role v2",
            "job_description": "new jd",
            "google_sheet_id": "NEWSHEET",
            "status": "closed",
            "rubric": {"job_title": "Y", "criteria": [{"name": "z", "weight": 2.0}]},
        },
    )
    assert resp.status_code == 200
    b = resp.json()
    assert b["title"] == "Role v2"
    assert b["job_description"] == "new jd"
    assert b["google_sheet_id"] == "NEWSHEET"
    assert b["status"] == "closed"
    assert b["rubric"]["criteria"][0]["name"] == "z"


def test_patch_invalid_rubric_400(api):
    jid = _create("Role").json()["id"]
    resp = client.patch(f"/jobs/{jid}", json={"rubric": {"job_title": "Y", "criteria": []}})
    assert resp.status_code == 400


def test_patch_unknown_404(api):
    assert client.patch("/jobs/nope", json={"title": "x"}).status_code == 404


def test_close_sets_status_closed(api):
    jid = _create("Role").json()["id"]
    resp = client.post(f"/jobs/{jid}/close")
    assert resp.status_code == 200
    assert resp.json()["status"] == "closed"
    # Reflected on GET.
    assert client.get(f"/jobs/{jid}").json()["status"] == "closed"


def test_close_unknown_404(api):
    assert client.post("/jobs/nope/close").status_code == 404


# --------------------------------------------------------------------------- #
# Repository update
# --------------------------------------------------------------------------- #
def test_repo_update_missing_raises(tmp_path):
    repo = JSONJobRepository(path=tmp_path / "jobs.json")
    job = Job(id="j1", title="T", job_description="jd", rubric=Rubric.model_validate(_rubric_payload()))
    with pytest.raises(KeyError):
        repo.update(job)
    repo.add(job)
    repo.update(job.model_copy(update={"status": JobStatus.closed}))
    assert repo.get("j1").status is JobStatus.closed


# --------------------------------------------------------------------------- #
# build_intake_source_for_job
# --------------------------------------------------------------------------- #
def _job(**extra) -> Job:
    return Job(
        id="j",
        title="T",
        job_description="jd",
        rubric=Rubric.model_validate(_rubric_payload()),
        **extra,
    )


def test_intake_source_google_when_sheet_set():
    src = build_intake_source_for_job(_job(google_sheet_id="SHEET-A"))
    assert isinstance(src, GoogleFormsIntakeSource)
    assert src.sheet_id == "SHEET-A"  # bound to THIS sheet, not env


def test_intake_source_local_when_no_sheet():
    src = build_intake_source_for_job(_job())
    assert isinstance(src, LocalFixtureIntakeSource)


# --------------------------------------------------------------------------- #
# Per-job dedup: same CV under two jobs ingests once per job
# --------------------------------------------------------------------------- #
def test_per_job_dedup(tmp_path):
    base = tmp_path / "cvs"
    base.mkdir()
    shutil.copyfile(SAMPLE_DIR / "sample_cv_text.pdf", base / "cv.pdf")

    csv_path = tmp_path / "responses.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["timestamp", "name", "email", "cv_filename", "job_id"])
        w.writerow(["2026-01-01 09:00:00", "Alice", "a@x.com", "cv.pdf", "job-a"])
        w.writerow(["2026-01-01 09:00:00", "Alice", "a@x.com", "cv.pdf", "job-b"])

    store = JSONCandidateStore(path=tmp_path / "candidates.json")
    rubric = Rubric.model_validate(_rubric_payload())

    def source():
        return LocalFixtureIntakeSource(csv_path=csv_path, base_dir=base)

    a = run_ingestion("jd", rubric, job_id="job-a", intake_source=source(), store=store)
    b = run_ingestion("jd", rubric, job_id="job-b", intake_source=source(), store=store)
    assert a.processed == 1 and b.processed == 1

    records = store.list_all()
    assert len(records) == 2  # same CV, two openings -> two records
    assert {r.candidate.job_id for r in records} == {"job-a", "job-b"}
    assert len({r.candidate.id for r in records}) == 2  # distinct scoped ids
    # Same underlying CV.
    assert len({r.candidate.file_hash for r in records}) == 1

    # Re-running job-a skips its own duplicate; job-b untouched.
    again = run_ingestion("jd", rubric, job_id="job-a", intake_source=source(), store=store)
    assert again.processed == 0 and again.skipped == 1
    assert len(store.list_all()) == 2
