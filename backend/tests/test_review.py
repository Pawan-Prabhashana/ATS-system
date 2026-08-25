"""Phase 4: artifact persistence + detail/decision endpoints + store round-trip."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.intake.local_fixture import LocalFixtureIntakeSource
from app.main import app
from app.models import Candidate, CandidateStatus, Evaluation, Job, Recommendation
from app.pipeline import load_default_job_description, load_default_rubric, run_site_ingestion
from app.store import JSONCandidateStore

client = TestClient(app)


@pytest.fixture
def store(tmp_path):
    return JSONCandidateStore(path=tmp_path / "candidates.json")


@pytest.fixture
def jd_and_rubric():
    return load_default_job_description(), load_default_rubric()


# --------------------------------------------------------------------------- #
# 1. Artifact persistence
# --------------------------------------------------------------------------- #
def test_ingestion_persists_cv_and_page_images(store, jd_and_rubric):
    jd, rubric = jd_and_rubric
    jobs = [
        Job(id="backend-engineer", title="Backend Engineer", role_key="Backend Engineer", job_description=jd, rubric=rubric),
        Job(id="graphic-designer", title="Graphic Designer", role_key="Graphic Design Intern", job_description=jd, rubric=rubric),
    ]
    run_site_ingestion(jobs, intake_source=LocalFixtureIntakeSource(), store=store)

    records = store.list_all()
    assert len(records) == 4  # Backend x3 + Graphic x1 (Motion Designer held)
    for record in records:
        # New stable-artifact fields are populated.
        assert record.artifact_dir == f"candidates/{record.candidate.id}"
        assert record.cv_file == "cv.pdf"
        assert record.page_image_files  # at least one page image

        # Files actually landed on disk under data/candidates/<id>/.
        cand_dir = settings.data_dir / "candidates" / record.candidate.id
        assert (cand_dir / "cv.pdf").exists()
        for name in record.page_image_files:
            assert (cand_dir / name).exists()
        # Page image names are normalised page_1.*, page_2.*, ...
        assert record.page_image_files[0].startswith("page_1")


# --------------------------------------------------------------------------- #
# 2. Store decision round-trip
# --------------------------------------------------------------------------- #
def _seed(store) -> str:
    cand = Candidate(id="c1", name="Alice", email="a@x.com", cv_filename="c1.pdf", file_hash="h1")
    ev = Evaluation(
        candidate_id="c1",
        criterion_scores=[],
        overall_score=72.0,
        recommendation=Recommendation.shortlist,
        summary="s",
        evaluated_by="mock",
    )
    store.upsert(cand, None, ev)
    return "c1"


def test_update_decision_shortlist_round_trips(store):
    cid = _seed(store)
    returned = store.update_decision(cid, "shortlist", "great portfolio")
    assert returned.candidate.status is CandidateStatus.shortlisted

    reloaded = store.get(cid)
    assert reloaded.candidate.status is CandidateStatus.shortlisted
    assert reloaded.candidate.reviewer_note == "great portfolio"
    assert reloaded.candidate.decided_at is not None


def test_update_decision_reject_round_trips(store):
    cid = _seed(store)
    store.update_decision(cid, "reject", None)
    reloaded = store.get(cid)
    assert reloaded.candidate.status is CandidateStatus.rejected
    assert reloaded.candidate.reviewer_note is None
    assert reloaded.candidate.decided_at is not None


def test_update_decision_invalid_value_raises(store):
    cid = _seed(store)
    with pytest.raises(ValueError):
        store.update_decision(cid, "maybe", None)


def test_update_decision_missing_candidate_raises(store):
    with pytest.raises(KeyError):
        store.update_decision("nope", "shortlist", None)


def test_change_decision_is_allowed(store):
    cid = _seed(store)
    store.update_decision(cid, "shortlist", "first take")
    store.update_decision(cid, "reject", "changed my mind")
    reloaded = store.get(cid)
    assert reloaded.candidate.status is CandidateStatus.rejected
    assert reloaded.candidate.reviewer_note == "changed my mind"


# --------------------------------------------------------------------------- #
# 3. API endpoints
# --------------------------------------------------------------------------- #
@pytest.fixture
def api_store(tmp_path, monkeypatch):
    from app.store import JSONJobRepository, seed_jobs

    monkeypatch.setenv("CATALIST_CANDIDATE_STORE_PATH", str(tmp_path / "candidates.json"))
    monkeypatch.setenv("CATALIST_JOB_STORE_PATH", str(tmp_path / "jobs.json"))
    monkeypatch.delenv("EVALUATOR_MODE", raising=False)
    monkeypatch.delenv("INTAKE_MODE", raising=False)
    seed_jobs(JSONJobRepository(path=tmp_path / "jobs.json"))


def _ingest_via_api() -> list[dict]:
    assert client.post("/ingest").status_code == 200
    resp = client.get("/candidates")
    assert resp.status_code == 200
    return resp.json()


def test_get_candidate_detail_200(api_store):
    records = _ingest_via_api()
    cid = records[0]["candidate"]["id"]

    resp = client.get(f"/candidates/{cid}")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["candidate"]["id"] == cid
    assert detail["evaluation"] is not None
    assert detail["evaluation"]["criterion_scores"]  # evidence-backed scores present
    assert detail["cv_url"] == f"/media/candidates/{cid}/cv.pdf"
    assert detail["page_image_urls"]
    assert detail["page_image_urls"][0].startswith(f"/media/candidates/{cid}/page_1")


def test_get_candidate_detail_404(api_store):
    resp = client.get("/candidates/does-not-exist")
    assert resp.status_code == 404


def test_patch_decision_success(api_store):
    records = _ingest_via_api()
    cid = records[0]["candidate"]["id"]

    resp = client.patch(
        f"/candidates/{cid}/decision",
        json={"decision": "shortlist", "note": "strong match"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["candidate"]["status"] == "shortlisted"
    assert body["candidate"]["reviewer_note"] == "strong match"
    assert body["candidate"]["decided_at"] is not None

    # Reflected back in the list view.
    listed = {r["candidate"]["id"]: r for r in client.get("/candidates").json()}
    assert listed[cid]["candidate"]["status"] == "shortlisted"


def test_patch_decision_invalid_value_400(api_store):
    records = _ingest_via_api()
    cid = records[0]["candidate"]["id"]
    resp = client.patch(f"/candidates/{cid}/decision", json={"decision": "banana"})
    assert resp.status_code == 400


def test_patch_decision_not_found_404(api_store):
    resp = client.patch("/candidates/ghost/decision", json={"decision": "reject"})
    assert resp.status_code == 404
