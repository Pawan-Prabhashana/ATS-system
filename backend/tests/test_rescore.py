"""Re-scoring an ingested candidate against its job's current rubric."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.store import JSONJobRepository, seed_jobs

client = TestClient(app)


@pytest.fixture
def ingested(tmp_path, monkeypatch):
    """Render-mode ingest via the API so candidates with local CVs exist."""
    monkeypatch.setenv("CATALIST_JOB_STORE_PATH", str(tmp_path / "jobs.json"))
    monkeypatch.setenv("CATALIST_CANDIDATE_STORE_PATH", str(tmp_path / "candidates.json"))
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path / "data")
    monkeypatch.delenv("EVALUATOR_MODE", raising=False)  # mock evaluator
    monkeypatch.delenv("INTAKE_MODE", raising=False)  # local fixture
    monkeypatch.setenv("CV_MODE", "render")
    seed_jobs(JSONJobRepository(path=tmp_path / "jobs.json"))
    assert client.post("/ingest").status_code == 200
    return client.get("/candidates").json()


def test_rescore_one_returns_fresh_evaluation(ingested):
    cid = ingested[0]["candidate"]["id"]
    resp = client.post(f"/candidates/{cid}/rescore")
    assert resp.status_code == 200
    body = resp.json()
    assert body["evaluation"] is not None
    assert body["candidate"]["id"] == cid


def test_rescore_unknown_candidate_404():
    assert client.post("/candidates/ghost/rescore").status_code == 404


def test_ingest_progress_endpoint_shape():
    # Before any background pull this session it's idle; shape is always a dict.
    body = client.get("/ingest/progress").json()
    assert "status" in body


def test_rescore_progress_unknown_job_404():
    assert client.post("/jobs/ghost/rescore/start").status_code == 404
