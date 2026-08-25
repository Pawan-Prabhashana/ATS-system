"""API tests for the site-level POST /ingest + listing (offline, mock+local)."""
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


def test_old_per_job_ingest_endpoint_is_gone():
    # Per-job ingest was replaced by the single site-level POST /ingest.
    assert client.post("/jobs/backend-engineer/ingest").status_code == 404


def test_site_ingest_then_list_ranked():
    resp = client.post("/ingest")
    assert resp.status_code == 200
    summary = resp.json()
    assert summary["processed_by_job"] == {"backend-engineer": 3, "graphic-designer": 1}
    assert summary["held_by_role"] == {"Motion Designer": 1}
    assert summary["failed"] == 0

    records = client.get("/jobs/backend-engineer/candidates").json()
    assert len(records) == 3
    scores = [r["evaluation"]["overall_score"] for r in records]
    assert scores == sorted(scores, reverse=True)


def test_site_ingest_is_idempotent():
    first = client.post("/ingest").json()
    assert first["processed"] == 4
    second = client.post("/ingest").json()
    assert second["processed"] == 0
    assert second["skipped_duplicate"] == 4
    assert second["held_by_role"] == {"Motion Designer": 1}
    assert len(client.get("/jobs/backend-engineer/candidates").json()) == 3
