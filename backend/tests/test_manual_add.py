"""Manually adding a candidate to a job by uploading a CV (no form)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.store import JSONJobRepository, seed_jobs

client = TestClient(app)


@pytest.fixture
def job(tmp_path, monkeypatch):
    monkeypatch.setenv("CATALIST_JOB_STORE_PATH", str(tmp_path / "jobs.json"))
    monkeypatch.setenv("CATALIST_CANDIDATE_STORE_PATH", str(tmp_path / "candidates.json"))
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path / "data")
    monkeypatch.delenv("EVALUATOR_MODE", raising=False)  # mock evaluator
    monkeypatch.setenv("CV_MODE", "render")
    seed_jobs(JSONJobRepository(path=tmp_path / "jobs.json"))
    return "backend-engineer"


def _cv_bytes() -> bytes:
    path = settings.sample_data_dir / "sample_cv_text.pdf"
    if not path.exists():
        pytest.skip("sample CV missing")
    return path.read_bytes()


def test_add_candidate_uploads_scores_and_stores(job):
    resp = client.post(
        f"/jobs/{job}/candidates",
        files={"file": ("alice.pdf", _cv_bytes(), "application/pdf")},
        data={"name": "Alice Uploaded", "email": "alice@example.com", "portfolio_url": "https://x.dev"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["candidate"]["name"] == "Alice Uploaded"
    assert body["candidate"]["email"] == "alice@example.com"
    assert body["candidate"]["portfolio_url"] == "https://x.dev"
    assert body["candidate"]["job_id"] == job
    assert body["evaluation"] is not None
    # The CV is retrievable (served from the local PDF, no Drive id).
    assert body["cv_pdf_url"]


def test_add_same_cv_twice_is_noop(job):
    files = {"file": ("a.pdf", _cv_bytes(), "application/pdf")}
    first = client.post(f"/jobs/{job}/candidates", files=files, data={"name": "A"})
    assert first.status_code == 201
    files = {"file": ("a.pdf", _cv_bytes(), "application/pdf")}
    second = client.post(f"/jobs/{job}/candidates", files=files, data={"name": "A again"})
    assert second.status_code == 201
    assert second.json()["candidate"]["id"] == first.json()["candidate"]["id"]


def test_add_non_pdf_is_400(job):
    resp = client.post(
        f"/jobs/{job}/candidates",
        files={"file": ("notes.txt", b"just text, not a pdf", "text/plain")},
    )
    assert resp.status_code == 400


def test_add_to_unknown_job_404():
    resp = client.post(
        "/jobs/ghost/candidates",
        files={"file": ("a.pdf", _cv_bytes(), "application/pdf")},
    )
    assert resp.status_code == 404
