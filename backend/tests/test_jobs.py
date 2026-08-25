"""Job model, repository, seeding, and job CRUD API (offline)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Job, Rubric
from app.store import JSONJobRepository, ensure_jobs_seeded, load_seed_jobs, seed_jobs

client = TestClient(app)


def _rubric() -> Rubric:
    return Rubric(job_title="X", criteria=[{"name": "c", "weight": 1.0}])


def _job(job_id="j1") -> Job:
    return Job(id=job_id, title="Role", job_description="jd", rubric=_rubric())


# --------------------------------------------------------------------------- #
# Repository
# --------------------------------------------------------------------------- #
@pytest.fixture
def repo(tmp_path):
    return JSONJobRepository(path=tmp_path / "jobs.json")


def test_add_get_list(repo):
    repo.add(_job("a"))
    repo.add(_job("b"))
    assert repo.get("a").id == "a"
    assert repo.get("missing") is None
    assert {j.id for j in repo.list_all()} == {"a", "b"}


def test_duplicate_id_raises(repo):
    repo.add(_job("a"))
    with pytest.raises(ValueError):
        repo.add(_job("a"))


def test_atomic_write_no_temp_leftovers(repo, tmp_path):
    repo.add(_job("a"))
    assert list(tmp_path.glob(".jobs-*.tmp")) == []
    # File round-trips.
    assert JSONJobRepository(path=repo.path).get("a").title == "Role"


# --------------------------------------------------------------------------- #
# Seeding
# --------------------------------------------------------------------------- #
def test_load_seed_jobs_reads_two_jobs():
    jobs = load_seed_jobs()
    ids = {j.id for j in jobs}
    assert ids == {"backend-engineer", "graphic-designer"}
    # Rubrics resolved from their files: design one requires visual review.
    by_id = {j.id: j for j in jobs}
    assert by_id["graphic-designer"].rubric.requires_visual_review is True
    assert by_id["backend-engineer"].rubric.requires_visual_review is False


def test_seed_jobs_is_idempotent(repo):
    added = seed_jobs(repo)
    assert len(added) == 2
    assert seed_jobs(repo) == []  # nothing new the second time
    assert len(repo.list_all()) == 2


def test_ensure_seeded_only_when_empty(repo):
    assert len(ensure_jobs_seeded(repo)) == 2
    assert ensure_jobs_seeded(repo) == []  # already populated -> no-op


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("CATALIST_JOB_STORE_PATH", str(tmp_path / "jobs.json"))


def test_jobs_crud_api(api):
    assert client.get("/jobs").json() == []  # empty to start

    body = {
        "title": "Data Scientist",
        "job_description": "Build models.",
        "role_key": "Data Scientist",
        "rubric": _rubric().model_dump(),
    }
    resp = client.post("/jobs", json=body)
    assert resp.status_code == 201
    assert resp.json()["id"] == "data-scientist"  # auto-slugged from title
    assert resp.json()["status"] == "open"

    assert client.get("/jobs/data-scientist").status_code == 200
    assert client.get("/jobs/missing").status_code == 404
    assert len(client.get("/jobs").json()) == 1

    # Same title again -> a fresh job with a suffixed id (distinct role_key).
    resp2 = client.post("/jobs", json={**body, "role_key": "Senior Data Scientist"})
    assert resp2.status_code == 201
    assert resp2.json()["id"] == "data-scientist-2"
    assert len(client.get("/jobs").json()) == 2
