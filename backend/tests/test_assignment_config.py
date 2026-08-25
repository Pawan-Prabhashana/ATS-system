"""Phase 9A: per-job brief, send integrity, decision undo (offline)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.models import Candidate, CandidateStatus, Evaluation, Recommendation
from app.store import JSONCandidateStore

client = TestClient(app)

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


@pytest.fixture(autouse=True)
def _stores(tmp_path, monkeypatch):
    monkeypatch.setenv("CATALIST_CANDIDATE_STORE_PATH", str(tmp_path / "candidates.json"))
    monkeypatch.setenv("CATALIST_JOB_STORE_PATH", str(tmp_path / "jobs.json"))
    monkeypatch.delenv("EMAIL_MODE", raising=False)


def _make_job(**extra) -> str:
    body = {
        "title": "Backend Engineer",
        "job_description": "jd",
        "role_key": "Backend Engineer",
        "rubric": {"job_title": "B", "criteria": [{"name": "c", "weight": 1.0}]},
        **extra,
    }
    return client.post("/jobs", json=body).json()["id"]


def _seed(cid: str, job_id: str, status: CandidateStatus, tier: Recommendation | None = None):
    ev = None
    if tier is not None:
        ev = Evaluation(
            candidate_id=cid,
            criterion_scores=[],
            overall_score=50.0,
            recommendation=tier,
            summary="s",
            evaluated_by="mock",
        )
    JSONCandidateStore().upsert(
        Candidate(
            id=cid,
            name="Cand",
            email=f"{cid}@example.com",
            cv_filename="c.pdf",
            file_hash=f"h-{cid}",
            job_id=job_id,
            status=status,
        ),
        None,
        ev,
    )


def _upload_brief(job_id: str, data: bytes = PDF, filename: str = "brief.pdf"):
    return client.post(
        f"/jobs/{job_id}/assignment-brief",
        files={"file": (filename, data, "application/pdf")},
    )


def _outbox(cid: str):
    return list((settings.data_dir / "outbox").glob(f"{cid}_*.json"))


# --------------------------------------------------------------------------- #
# Brief upload / get / delete
# --------------------------------------------------------------------------- #
def test_brief_upload_rejects_non_pdf():
    jid = _make_job()
    resp = client.post(
        f"/jobs/{jid}/assignment-brief",
        files={"file": ("notes.txt", b"just text, not a pdf", "text/plain")},
    )
    assert resp.status_code == 400
    assert "pdf" in resp.json()["detail"].lower()


def test_brief_upload_get_delete_roundtrip():
    jid = _make_job()
    assert client.get(f"/jobs/{jid}/assignment-brief").status_code == 404  # none yet

    resp = _upload_brief(jid, filename="take_home.pdf")
    assert resp.status_code == 200
    assert resp.json()["assignment_brief_filename"] == "take_home.pdf"

    got = client.get(f"/jobs/{jid}/assignment-brief")
    assert got.status_code == 200
    assert got.headers["content-type"] == "application/pdf"

    deleted = client.delete(f"/jobs/{jid}/assignment-brief")
    assert deleted.status_code == 200
    assert deleted.json()["assignment_brief_filename"] is None
    assert client.get(f"/jobs/{jid}/assignment-brief").status_code == 404


# --------------------------------------------------------------------------- #
# Send needs the job's brief
# --------------------------------------------------------------------------- #
def test_single_send_without_brief_is_409_then_works_after_upload():
    jid = _make_job()
    _seed("s1", jid, CandidateStatus.shortlisted)

    blocked = client.post("/candidates/s1/send-assignment")
    assert blocked.status_code == 409
    assert "brief" in blocked.json()["detail"].lower()
    assert _outbox("s1") == []  # no email went out
    assert JSONCandidateStore().get("s1").candidate.status is CandidateStatus.shortlisted

    _upload_brief(jid, filename="the_task.pdf")
    ok = client.post("/candidates/s1/send-assignment")
    assert ok.status_code == 200
    assert ok.json()["candidate"]["status"] == "assignment_sent"

    # The job's brief (its uploaded filename) is what's attached.
    files = _outbox("s1")
    assert len(files) == 1
    assert json.loads(files[0].read_text())["attachments"] == ["the_task.pdf"]


def test_bulk_no_brief_lands_in_skipped_not_failed():
    jid = _make_job()
    _seed("a", jid, CandidateStatus.shortlisted)
    _seed("b", jid, CandidateStatus.shortlisted)

    resp = client.post(f"/jobs/{jid}/send-assignments")
    assert resp.status_code == 200
    body = resp.json()
    assert body["sent_count"] == 0
    assert body["failed_count"] == 0  # not a failure — an expected skip
    assert body["skipped_count"] == 2
    assert all(o["status"] == "no_assignment_brief" for o in body["skipped"])


# --------------------------------------------------------------------------- #
# Send integrity — recommendation never changes; status never reverts
# --------------------------------------------------------------------------- #
def test_send_does_not_change_recommendation_or_revert():
    jid = _make_job()
    _seed("bord", jid, CandidateStatus.scored, tier=Recommendation.borderline)
    _upload_brief(jid)

    # Human shortlists an AI-borderline candidate.
    client.patch("/candidates/bord/decision", json={"decision": "shortlist"})

    sent = client.post("/candidates/bord/send-assignment")
    assert sent.status_code == 200
    body = sent.json()
    assert body["candidate"]["status"] == "assignment_sent"
    # The AI tier is untouched, and status did not revert.
    assert body["evaluation"]["recommendation"] == "borderline"

    reloaded = JSONCandidateStore().get("bord")
    assert reloaded.candidate.status is CandidateStatus.assignment_sent
    assert reloaded.evaluation.recommendation is Recommendation.borderline


# --------------------------------------------------------------------------- #
# Decision undo
# --------------------------------------------------------------------------- #
def test_decision_undo_returns_to_scored():
    jid = _make_job()
    _seed("u", jid, CandidateStatus.scored, tier=Recommendation.reject)

    client.patch("/candidates/u/decision", json={"decision": "shortlist", "note": "maybe"})
    mid = JSONCandidateStore().get("u").candidate
    assert mid.status is CandidateStatus.shortlisted
    assert mid.reviewer_note == "maybe" and mid.decided_at is not None

    resp = client.patch("/candidates/u/decision", json={"decision": "undecided"})
    assert resp.status_code == 200
    c = resp.json()["candidate"]
    assert c["status"] == "scored"
    assert c["reviewer_note"] is None
    assert c["decided_at"] is None


# --------------------------------------------------------------------------- #
# PATCH assignment config
# --------------------------------------------------------------------------- #
def test_patch_assignment_deadline_and_message():
    jid = _make_job()
    resp = client.patch(
        f"/jobs/{jid}",
        json={"assignment_deadline_days": 10, "assignment_message": "Good luck!"},
    )
    assert resp.status_code == 200
    assert resp.json()["assignment_deadline_days"] == 10
    assert resp.json()["assignment_message"] == "Good luck!"
