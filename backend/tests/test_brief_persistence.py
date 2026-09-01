"""The assignment brief must survive a restart that wipes local disk (Render's
filesystem is ephemeral). Bytes are stored in the DB; at send time, if the disk
file is gone, they're materialized to a temp file for the email attachment.
"""
from __future__ import annotations

import os

from app.email.base import EmailSendResult
from app.models import (
    Candidate,
    CandidateStatus,
    Evaluation,
    Job,
    Recommendation,
    Rubric,
)
from app.pipeline.assignment import SendOutcomeStatus, send_assignment_to_candidate
from app.store import JSONCandidateStore

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


class _StubJobRepo:
    def __init__(self, job):
        self._job = job

    def get(self, jid):
        return self._job if jid == self._job.id else None


class _CaptureSender:
    def __init__(self):
        self.attachment_existed = None
        self.attachment_bytes = None

    def send(self, message):
        att = message.attachments[0]
        self.attachment_existed = os.path.exists(att.path)
        with open(att.path, "rb") as fh:
            self.attachment_bytes = fh.read()
        return EmailSendResult(success=True, provider_message_id="x")


def test_send_materializes_brief_from_db_when_disk_gone(tmp_path, monkeypatch):
    # Fresh data dir -> the brief's disk file does NOT exist (simulates a restart).
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path / "data")

    store = JSONCandidateStore(path=tmp_path / "candidates.json")
    store.upsert(
        Candidate(
            id="s1", name="C", email="c@example.com", cv_filename="c.pdf",
            file_hash="h", job_id="j1", status=CandidateStatus.shortlisted,
        ),
        None,
        Evaluation(
            candidate_id="s1", criterion_scores=[], overall_score=50.0,
            recommendation=Recommendation.shortlist, summary="s", evaluated_by="mock",
        ),
    )
    job = Job(
        id="j1", title="T", role_key="T", job_description="jd",
        rubric=Rubric(job_title="B", criteria=[{"name": "c", "weight": 1.0}]),
        assignment_brief_filename="brief.pdf",
        assignment_brief_data=PDF,  # only in the DB; no disk file
    )
    sender = _CaptureSender()

    outcome = send_assignment_to_candidate(
        "s1", store=store, job_repo=_StubJobRepo(job), sender=sender
    )

    assert outcome.status is SendOutcomeStatus.sent
    assert sender.attachment_existed is True  # temp file was materialized
    assert sender.attachment_bytes == PDF
    assert store.get("s1").candidate.status is CandidateStatus.assignment_sent


def test_send_blocks_when_no_brief_bytes_and_no_disk(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path / "data")
    store = JSONCandidateStore(path=tmp_path / "candidates.json")
    store.upsert(
        Candidate(id="s2", name="C", email="c@example.com", cv_filename="c.pdf",
                  file_hash="h2", job_id="j1", status=CandidateStatus.shortlisted),
        None,
        Evaluation(candidate_id="s2", criterion_scores=[], overall_score=50.0,
                   recommendation=Recommendation.shortlist, summary="s", evaluated_by="mock"),
    )
    # Brief metadata present but NO bytes and NO disk file -> clean block, not a crash.
    job = Job(id="j1", title="T", role_key="T", job_description="jd",
              rubric=Rubric(job_title="B", criteria=[{"name": "c", "weight": 1.0}]),
              assignment_brief_filename="brief.pdf", assignment_brief_data=None)
    outcome = send_assignment_to_candidate("s2", store=store, job_repo=_StubJobRepo(job), sender=_CaptureSender())
    assert outcome.status is SendOutcomeStatus.no_assignment_brief
