"""API tests for job-scoped ingestion + listing (offline, mock+local)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.store import JSONJobRepository, seed_jobs

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("CATALIST_CANDIDATE_STORE_PATH", str(tmp_path / "candidates.json"))
    monkeypatch.setenv("CATALIST_JOB_STORE_PATH", str(tmp_path / "jobs.json"))
    monkeypatch.delenv("EVALUATOR_MODE", raising=False)
    monkeypatch.delenv("INTAKE_MODE", raising=False)
    seed_jobs(JSONJobRepository(path=tmp_path / "jobs.json"))


def test_old_global_ingest_endpoint_is_gone():
    # The global POST /ingest was removed in favour of POST /jobs/{id}/ingest.
    assert client.post("/ingest").status_code == 404


def test_job_scoped_ingest_then_list_ranked():
    resp = client.post("/jobs/backend-engineer/ingest")
    assert resp.status_code == 200
    summary = resp.json()
    assert summary["processed"] == 3
    assert summary["failed"] == 0

    resp = client.get("/jobs/backend-engineer/candidates")
    assert resp.status_code == 200
    records = resp.json()
    assert len(records) == 3
    scores = [r["evaluation"]["overall_score"] for r in records]
    assert scores == sorted(scores, reverse=True)


def test_ingest_unknown_job_404():
    assert client.post("/jobs/nope/ingest").status_code == 404


def test_ingest_is_idempotent_per_job():
    first = client.post("/jobs/backend-engineer/ingest").json()
    assert first["processed"] == 3
    second = client.post("/jobs/backend-engineer/ingest").json()
    assert second["processed"] == 0
    assert second["skipped"] == 3
    assert len(client.get("/jobs/backend-engineer/candidates").json()) == 3
