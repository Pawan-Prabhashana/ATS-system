"""Job config as first-class data + role_key routing (Phase 15, offline)."""
from __future__ import annotations

import csv
import shutil

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.intake.google_forms import GoogleFormsIntakeSource
from app.intake.local_fixture import LocalFixtureIntakeSource
from app.main import app
from app.models import Job, JobStatus, Rubric
from app.pipeline import build_intake_source_for_job, run_site_ingestion
from app.store import JSONCandidateStore, JSONJobRepository

client = TestClient(app)

SAMPLE_DIR = settings.sample_data_dir


def _rubric_payload() -> dict:
    return {"job_title": "X", "criteria": [{"name": "c", "weight": 1.0}]}


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("CATALIST_JOB_STORE_PATH", str(tmp_path / "jobs.json"))
    monkeypatch.setenv("CATALIST_CANDIDATE_STORE_PATH", str(tmp_path / "candidates.json"))


def _create(title="Senior Backend Engineer", role_key=None, **extra):
    body = {
        "title": title,
        "job_description": "jd",
        "rubric": _rubric_payload(),
        "role_key": role_key if role_key is not None else title,  # unique per title by default
        **extra,
    }
    return client.post("/jobs", json=body)


# --------------------------------------------------------------------------- #
# Create: auto-slug, role_key required + unique, validation
# --------------------------------------------------------------------------- #
def test_create_auto_slugs_id(api):
    resp = _create("Senior Backend Engineer!", role_key="Senior Backend Engineer")
    assert resp.status_code == 201
    assert resp.json()["id"] == "senior-backend-engineer"
    assert resp.json()["role_key"] == "Senior Backend Engineer"


def test_create_requires_role_key(api):
    # role_key missing -> 422 (required by the request model).
    resp = client.post("/jobs", json={"title": "T", "job_description": "jd", "rubric": _rubric_payload()})
    assert resp.status_code == 422


def test_create_collision_suffixing_with_distinct_roles(api):
    # Same title -> suffixed ids; each still serves a DISTINCT role_key.
    assert _create("Designer", role_key="Designer A").json()["id"] == "designer"
    assert _create("Designer", role_key="Designer B").json()["id"] == "designer-2"
    assert _create("Designer", role_key="Designer C").json()["id"] == "designer-3"


def test_create_duplicate_role_key_400(api):
    assert _create("Designer", role_key="Graphic Design Intern").status_code == 201
    resp = _create("Another Designer", role_key="Graphic Design Intern")
    assert resp.status_code == 400
    assert "role_key" in resp.json()["detail"].lower()


def test_create_status(api):
    resp = _create("Data Eng", role_key="Data Engineer", status="closed")
    assert resp.status_code == 201
    assert resp.json()["status"] == "closed"


@pytest.mark.parametrize(
    "bad_rubric",
    [
        {"job_title": "X", "criteria": []},
        {"job_title": "X", "criteria": [{"name": "c", "weight": 0}]},
        {"job_title": "X", "criteria": [{"name": "c", "weight": -1}]},
    ],
)
def test_create_rejects_invalid_rubric_400(api, bad_rubric):
    resp = client.post(
        "/jobs",
        json={"title": "T", "job_description": "jd", "rubric": bad_rubric, "role_key": "T-role"},
    )
    assert resp.status_code == 400
    assert "rubric" in resp.json()["detail"].lower()


# --------------------------------------------------------------------------- #
# PATCH + close
# --------------------------------------------------------------------------- #
def test_patch_updates_each_field(api):
    jid = _create("Role", role_key="Role One").json()["id"]

    resp = client.patch(
        f"/jobs/{jid}",
        json={
            "title": "Role v2",
            "job_description": "new jd",
            "role_key": "Role Two",
            "status": "closed",
            "rubric": {"job_title": "Y", "criteria": [{"name": "z", "weight": 2.0}]},
        },
    )
    assert resp.status_code == 200
    b = resp.json()
    assert b["title"] == "Role v2"
    assert b["job_description"] == "new jd"
    assert b["role_key"] == "Role Two"
    assert b["status"] == "closed"
    assert b["rubric"]["criteria"][0]["name"] == "z"


def test_patch_duplicate_role_key_400(api):
    _create("A", role_key="Role A")
    jid = _create("B", role_key="Role B").json()["id"]
    resp = client.patch(f"/jobs/{jid}", json={"role_key": "Role A"})
    assert resp.status_code == 400


def test_patch_invalid_rubric_400(api):
    jid = _create("Role", role_key="Role X").json()["id"]
    resp = client.patch(f"/jobs/{jid}", json={"rubric": {"job_title": "Y", "criteria": []}})
    assert resp.status_code == 400


def test_patch_unknown_404(api):
    assert client.patch("/jobs/nope", json={"title": "x"}).status_code == 404


def test_close_sets_status_closed(api):
    jid = _create("Role", role_key="Role Close").json()["id"]
    resp = client.post(f"/jobs/{jid}/close")
    assert resp.status_code == 200
    assert resp.json()["status"] == "closed"
    assert client.get(f"/jobs/{jid}").json()["status"] == "closed"


def test_close_unknown_404(api):
    assert client.post("/jobs/nope/close").status_code == 404


# --------------------------------------------------------------------------- #
# Repository update
# --------------------------------------------------------------------------- #
def test_repo_update_missing_raises(tmp_path):
    repo = JSONJobRepository(path=tmp_path / "jobs.json")
    job = Job(id="j1", title="T", role_key="R", job_description="jd", rubric=Rubric.model_validate(_rubric_payload()))
    with pytest.raises(KeyError):
        repo.update(job)
    repo.add(job)
    repo.update(job.model_copy(update={"status": JobStatus.closed}))
    assert repo.get("j1").status is JobStatus.closed


# --------------------------------------------------------------------------- #
# build_intake_source_for_job (legacy helper still exists)
# --------------------------------------------------------------------------- #
def _job(**extra) -> Job:
    return Job(id="j", title="T", role_key="R", job_description="jd", rubric=Rubric.model_validate(_rubric_payload()), **extra)


def test_intake_source_google_when_sheet_set():
    src = build_intake_source_for_job(_job(google_sheet_id="SHEET-A"))
    assert isinstance(src, GoogleFormsIntakeSource)


def test_intake_source_local_when_no_sheet():
    assert isinstance(build_intake_source_for_job(_job()), LocalFixtureIntakeSource)


# --------------------------------------------------------------------------- #
# Per-(job, file_hash) dedup: same CV under two roles -> two jobs -> two records
# --------------------------------------------------------------------------- #
def test_per_job_dedup_across_roles(tmp_path):
    base = tmp_path / "cvs"
    base.mkdir()
    shutil.copyfile(SAMPLE_DIR / "sample_cv_text.pdf", base / "cv.pdf")

    csv_path = tmp_path / "responses.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["timestamp", "name", "email", "cv_filename", "role"])
        w.writerow(["2026-01-01 09:00:00", "Alice", "a@x.com", "cv.pdf", "Role A"])
        w.writerow(["2026-01-01 09:00:00", "Alice", "a@x.com", "cv.pdf", "Role B"])

    store = JSONCandidateStore(path=tmp_path / "candidates.json")
    rubric = Rubric.model_validate(_rubric_payload())
    jobs = [
        Job(id="job-a", title="A", role_key="Role A", job_description="jd", rubric=rubric),
        Job(id="job-b", title="B", role_key="Role B", job_description="jd", rubric=rubric),
    ]

    def source():
        return LocalFixtureIntakeSource(csv_path=csv_path, base_dir=base)

    s1 = run_site_ingestion(jobs, intake_source=source(), store=store)
    assert s1.processed == 2
    assert s1.processed_by_job == {"job-a": 1, "job-b": 1}

    records = store.list_all()
    assert len(records) == 2  # same CV, two roles -> two records
    assert {r.candidate.job_id for r in records} == {"job-a", "job-b"}
    assert len({r.candidate.file_hash for r in records}) == 1  # same underlying CV

    # Re-running skips both as duplicates.
    s2 = run_site_ingestion(jobs, intake_source=source(), store=store)
    assert s2.processed == 0 and s2.skipped_duplicate == 2
    assert len(store.list_all()) == 2
