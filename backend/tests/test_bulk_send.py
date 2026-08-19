"""Phase 6: bulk assignment send (offline — mock outbox + injected senders)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.email import EmailSendResult
from app.main import app
from app.models import Candidate, CandidateStatus
from app.store import JSONCandidateStore, JSONJobRepository, seed_jobs

client = TestClient(app)

BACKEND = "backend-engineer"
DESIGN = "graphic-designer"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("CATALIST_CANDIDATE_STORE_PATH", str(tmp_path / "candidates.json"))
    monkeypatch.setenv("CATALIST_JOB_STORE_PATH", str(tmp_path / "jobs.json"))
    monkeypatch.delenv("EMAIL_MODE", raising=False)  # default mock
    seed_jobs(JSONJobRepository(path=tmp_path / "jobs.json"))
    # Expose the candidate store path for direct seeding.
    return tmp_path / "candidates.json"


def _seed(store_path: Path, cid: str, status: CandidateStatus, job_id: str = BACKEND):
    store = JSONCandidateStore(path=store_path)
    store.upsert(
        Candidate(
            id=cid,
            name=f"Cand {cid}",
            email=f"{cid}@example.com",
            cv_filename=f"{cid}.pdf",
            file_hash=f"h-{cid}",
            job_id=job_id,
            status=status,
        ),
        None,
        None,
    )


def _outbox_files(cid: str) -> list[Path]:
    return list((settings.data_dir / "outbox").glob(f"{cid}_*.json"))


# --------------------------------------------------------------------------- #
# Core partitioning
# --------------------------------------------------------------------------- #
def test_bulk_send_partitions_mixed_candidates(_isolated):
    store_path = _isolated
    _seed(store_path, "s1", CandidateStatus.shortlisted)
    _seed(store_path, "s2", CandidateStatus.shortlisted)
    _seed(store_path, "already", CandidateStatus.assignment_sent)
    _seed(store_path, "scored", CandidateStatus.scored)

    # Default target = all shortlisted in the job (s1, s2 only).
    resp = client.post(f"/jobs/{BACKEND}/send-assignments")
    assert resp.status_code == 200
    body = resp.json()
    assert body["requested_count"] == 2
    assert body["sent_count"] == 2
    assert {o["candidate_id"] for o in body["sent"]} == {"s1", "s2"}
    assert body["skipped_count"] == 0
    assert body["failed_count"] == 0

    # Personalized outbox files exist per sent candidate.
    for cid in ("s1", "s2"):
        files = _outbox_files(cid)
        assert len(files) == 1
        data = json.loads(files[0].read_text())
        assert data["to"] == f"{cid}@example.com"


def test_explicit_ids_partition_sent_skipped(_isolated):
    store_path = _isolated
    _seed(store_path, "s1", CandidateStatus.shortlisted)
    _seed(store_path, "already", CandidateStatus.assignment_sent)
    _seed(store_path, "scored", CandidateStatus.scored)

    resp = client.post(
        f"/jobs/{BACKEND}/send-assignments",
        json={"candidate_ids": ["s1", "already", "scored", "ghost"]},
    )
    body = resp.json()
    assert body["requested_count"] == 4
    assert {o["candidate_id"] for o in body["sent"]} == {"s1"}
    # already-sent (no force) + not-shortlisted -> skipped; ghost -> failed.
    skipped_status = {o["candidate_id"]: o["status"] for o in body["skipped"]}
    assert skipped_status["already"] == "skipped_already_sent"
    assert skipped_status["scored"] == "skipped_not_shortlisted"
    failed_ids = {o["candidate_id"] for o in body["failed"]}
    assert "ghost" in failed_ids


def test_candidate_from_other_job_is_excluded(_isolated):
    store_path = _isolated
    _seed(store_path, "mine", CandidateStatus.shortlisted, job_id=BACKEND)
    _seed(store_path, "theirs", CandidateStatus.shortlisted, job_id=DESIGN)

    resp = client.post(
        f"/jobs/{BACKEND}/send-assignments",
        json={"candidate_ids": ["mine", "theirs"]},
    )
    body = resp.json()
    assert {o["candidate_id"] for o in body["sent"]} == {"mine"}
    # 'theirs' is flagged wrong-job, not processed.
    wrong = [o for o in body["skipped"] if o["candidate_id"] == "theirs"]
    assert wrong and wrong[0]["status"] == "skipped_wrong_job"
    # It was NOT sent: no outbox file, status unchanged.
    assert _outbox_files("theirs") == []
    assert (
        JSONCandidateStore(path=store_path).get("theirs").candidate.status
        is CandidateStatus.shortlisted
    )


# --------------------------------------------------------------------------- #
# Failure isolation
# --------------------------------------------------------------------------- #
def test_failing_sender_isolates_failures(_isolated, monkeypatch):
    store_path = _isolated
    _seed(store_path, "a", CandidateStatus.shortlisted)
    _seed(store_path, "b", CandidateStatus.shortlisted)

    class _FailA:
        name = "faila"

        def send(self, message):
            if message.metadata.get("candidate_id") == "a":
                return EmailSendResult(success=False, error="boom for a")
            return EmailSendResult(success=True, provider_message_id="ok")

    monkeypatch.setattr("app.api.routes.get_email_sender", lambda: _FailA())

    body = client.post(f"/jobs/{BACKEND}/send-assignments").json()
    assert {o["candidate_id"] for o in body["failed"]} == {"a"}
    assert {o["candidate_id"] for o in body["sent"]} == {"b"}

    store = JSONCandidateStore(path=store_path)
    # a's status untouched; b advanced.
    assert store.get("a").candidate.status is CandidateStatus.shortlisted
    assert store.get("b").candidate.status is CandidateStatus.assignment_sent


# --------------------------------------------------------------------------- #
# Force resend
# --------------------------------------------------------------------------- #
def test_force_resends_already_sent_and_increments(_isolated):
    store_path = _isolated
    _seed(store_path, "s1", CandidateStatus.shortlisted)

    first = client.post(f"/jobs/{BACKEND}/send-assignments").json()
    assert first["sent_count"] == 1
    assert JSONCandidateStore(path=store_path).get("s1").candidate.assignment_sent_count == 1

    # Without force, the now-assignment_sent candidate is skipped.
    again = client.post(f"/jobs/{BACKEND}/send-assignments").json()
    assert again["requested_count"] == 0  # no shortlisted remain
    # With explicit id + force, it resends.
    forced = client.post(
        f"/jobs/{BACKEND}/send-assignments",
        json={"candidate_ids": ["s1"], "force": True},
    ).json()
    assert forced["sent_count"] == 1
    rec = JSONCandidateStore(path=store_path).get("s1")
    assert rec.candidate.assignment_sent_count == 2
    assert len(_outbox_files("s1")) == 2


# --------------------------------------------------------------------------- #
# Edge cases
# --------------------------------------------------------------------------- #
def test_zero_eligible_is_not_an_error(_isolated):
    store_path = _isolated
    _seed(store_path, "scored", CandidateStatus.scored)  # nobody shortlisted

    resp = client.post(f"/jobs/{BACKEND}/send-assignments")
    assert resp.status_code == 200
    body = resp.json()
    assert body["requested_count"] == 0
    assert body["sent"] == [] and body["skipped"] == [] and body["failed"] == []


def test_unknown_job_404(_isolated):
    assert client.post("/jobs/nope/send-assignments").status_code == 404


def test_bulk_send_only_targets_this_job_by_default(_isolated):
    store_path = _isolated
    _seed(store_path, "b1", CandidateStatus.shortlisted, job_id=BACKEND)
    _seed(store_path, "d1", CandidateStatus.shortlisted, job_id=DESIGN)

    body = client.post(f"/jobs/{BACKEND}/send-assignments").json()
    assert {o["candidate_id"] for o in body["sent"]} == {"b1"}
    assert _outbox_files("d1") == []  # design candidate untouched
