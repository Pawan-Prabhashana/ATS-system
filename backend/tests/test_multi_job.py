"""Multi-job isolation, tier/status filtering, and summary counts (offline)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.models import CandidateStatus, Recommendation
from app.main import app
from app.store import JSONJobRepository, seed_jobs

client = TestClient(app)

BACKEND = "backend-engineer"
DESIGN = "graphic-designer"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("CATALIST_CANDIDATE_STORE_PATH", str(tmp_path / "candidates.json"))
    monkeypatch.setenv("CATALIST_JOB_STORE_PATH", str(tmp_path / "jobs.json"))
    monkeypatch.delenv("EVALUATOR_MODE", raising=False)
    monkeypatch.delenv("INTAKE_MODE", raising=False)
    seed_jobs(JSONJobRepository(path=tmp_path / "jobs.json"))


def _ingest_both():
    assert client.post(f"/jobs/{BACKEND}/ingest").json()["processed"] == 3
    assert client.post(f"/jobs/{DESIGN}/ingest").json()["processed"] == 2


def _job_candidates(job_id, **params):
    resp = client.get(f"/jobs/{job_id}/candidates", params=params)
    assert resp.status_code == 200
    return resp.json()


# --------------------------------------------------------------------------- #
# Isolation
# --------------------------------------------------------------------------- #
def test_ingest_is_job_isolated():
    _ingest_both()

    backend = _job_candidates(BACKEND)
    design = _job_candidates(DESIGN)

    assert len(backend) == 3
    assert len(design) == 2

    backend_ids = {r["candidate"]["id"] for r in backend}
    design_ids = {r["candidate"]["id"] for r in design}
    assert backend_ids.isdisjoint(design_ids)  # no candidate appears in both

    assert all(r["candidate"]["job_id"] == BACKEND for r in backend)
    assert all(r["candidate"]["job_id"] == DESIGN for r in design)
    assert {r["candidate"]["email"] for r in design} == {
        "dana.lee@example.com",
        "miguel.torres@example.com",
    }
    # The global list has all 5.
    assert len(client.get("/candidates").json()) == 5


def test_listing_unknown_job_404():
    assert client.get("/jobs/nope/candidates").status_code == 404
    assert client.get("/jobs/nope/summary").status_code == 404


def test_candidates_ranked_by_score_desc():
    _ingest_both()
    scores = [r["evaluation"]["overall_score"] for r in _job_candidates(BACKEND)]
    assert scores == sorted(scores, reverse=True)


# --------------------------------------------------------------------------- #
# Filters — every tier/status combination, checked against locally-derived truth
# --------------------------------------------------------------------------- #
def test_all_tier_and_status_filter_combinations():
    _ingest_both()
    all_backend = _job_candidates(BACKEND)  # no filter -> everything

    def matches(rec, tier, status):
        if tier is not None and (
            rec["evaluation"] is None or rec["evaluation"]["recommendation"] != tier
        ):
            return False
        if status is not None and rec["candidate"]["status"] != status:
            return False
        return True

    tiers = [None] + [t.value for t in Recommendation]
    statuses = [None] + [s.value for s in CandidateStatus]

    for tier in tiers:
        for status in statuses:
            params = {}
            if tier is not None:
                params["tier"] = tier
            if status is not None:
                params["status"] = status
            got = {r["candidate"]["id"] for r in _job_candidates(BACKEND, **params)}
            expected = {
                r["candidate"]["id"] for r in all_backend if matches(r, tier, status)
            }
            assert got == expected, f"tier={tier} status={status}"


def test_tier_filter_isolates_by_job():
    _ingest_both()
    # A 'shortlist' filter on the design job never returns backend candidates.
    design_shortlist = _job_candidates(DESIGN, tier="shortlist")
    assert all(r["candidate"]["job_id"] == DESIGN for r in design_shortlist)


# --------------------------------------------------------------------------- #
# Summary
# --------------------------------------------------------------------------- #
def test_summary_counts_match_actual_data():
    _ingest_both()
    records = _job_candidates(BACKEND)

    expected_tier = {t.value: 0 for t in Recommendation}
    expected_status = {s.value: 0 for s in CandidateStatus}
    for r in records:
        if r["evaluation"] is not None:
            expected_tier[r["evaluation"]["recommendation"]] += 1
        expected_status[r["candidate"]["status"]] += 1

    resp = client.get(f"/jobs/{BACKEND}/summary")
    assert resp.status_code == 200
    summary = resp.json()
    assert summary["job_id"] == BACKEND
    assert summary["total"] == 3
    assert summary["by_tier"] == expected_tier
    assert summary["by_status"] == expected_status
    # Tier counts sum to the number of evaluated candidates.
    assert sum(summary["by_tier"].values()) == 3


# --------------------------------------------------------------------------- #
# Detail carries job context
# --------------------------------------------------------------------------- #
def test_candidate_detail_includes_job_context():
    _ingest_both()
    cid = _job_candidates(DESIGN)[0]["candidate"]["id"]
    detail = client.get(f"/candidates/{cid}").json()
    assert detail["job_id"] == DESIGN
    assert detail["job_title"] == "Graphic Designer"
