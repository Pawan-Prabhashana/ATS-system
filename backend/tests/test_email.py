"""Phase 5: assignment email dispatch (offline — mock outbox + stubbed Resend)."""
from __future__ import annotations

import base64
import json
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.config import settings
from app.email import (
    EmailAttachment,
    EmailConfigError,
    EmailMessage,
    EmailSendResult,
    MockEmailSender,
    ResendEmailSender,
    render_assignment_email,
)
from app.main import app
from app.models import Candidate, CandidateStatus, Job, Rubric
from app.store import JSONCandidateStore, JSONJobRepository
from tests.helpers import provision_brief

client = TestClient(app)

JOB_ID = "c-job"


# --------------------------------------------------------------------------- #
# Mock sender + template
# --------------------------------------------------------------------------- #
def test_mock_sender_writes_outbox_file():
    msg = EmailMessage(
        to="jane@example.com",
        to_name="Jane",
        subject="Hello",
        html_body="<p>Hi</p>",
        metadata={"candidate_id": "cand-9"},
    )
    result = MockEmailSender().send(msg)
    assert result.success and result.provider_message_id

    outbox = settings.data_dir / "outbox"
    files = list(outbox.glob("cand-9_*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    assert data["to"] == "jane@example.com"
    assert data["subject"] == "Hello"
    assert data["metadata"]["candidate_id"] == "cand-9"


def test_render_assignment_email_has_role_deadline_attachment(tmp_path):
    cand = Candidate(id="c1", name="Sam", email="sam@example.com", cv_filename="c.pdf", file_hash="h")
    deadline = date(2026, 8, 25)
    brief = tmp_path / "brief.pdf"
    brief.write_bytes(b"%PDF-1.4 fake")
    msg = render_assignment_email(
        cand, "Backend Engineer", deadline, brief, custom_message="A note from us."
    )
    assert msg.to == "sam@example.com"
    assert "Backend Engineer" in msg.subject
    assert "Sam" in msg.html_body
    assert "25 August 2026" in msg.html_body
    assert "A note from us." in msg.html_body  # custom per-job message
    assert [a.filename for a in msg.attachments] == ["assignment_brief.pdf"]
    assert msg.metadata["candidate_id"] == "c1"


# --------------------------------------------------------------------------- #
# ResendEmailSender — stubbed, no real key/network
# --------------------------------------------------------------------------- #
def test_resend_construct_without_key_does_not_raise(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("RESEND_FROM_EMAIL", raising=False)
    ResendEmailSender()  # must not raise


def test_resend_send_without_key_raises_config_error(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.setenv("RESEND_FROM_EMAIL", "hire@catalist.dev")
    msg = EmailMessage(to="a@b.com", subject="s", html_body="<p>x</p>")
    with pytest.raises(EmailConfigError):
        ResendEmailSender().send(msg)


def _sent_payload(route) -> dict:
    """Decode the JSON body the sender POSTed to Resend."""
    return json.loads(route.calls.last.request.content)


@respx.mock
def test_resend_send_success_payload_shape(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_notreal")
    monkeypatch.setenv("RESEND_FROM_EMAIL", "hire@catalist.dev")
    monkeypatch.delenv("RESEND_REPLY_TO", raising=False)
    route = respx.post("https://api.resend.com/emails").mock(
        return_value=httpx.Response(200, json={"id": "re_123"})
    )
    msg = EmailMessage(to="a@b.com", to_name="A", subject="s", html_body="<p>x</p>")
    result = ResendEmailSender().send(msg)

    assert route.call_count == 1
    assert result.success and result.provider_message_id == "re_123"

    payload = _sent_payload(route)
    assert payload["from"] == "hire@catalist.dev"  # from = RESEND_FROM_EMAIL
    assert payload["to"] == ["A <a@b.com>"]
    assert payload["subject"] == "s"
    assert payload["html"] == "<p>x</p>"
    assert "reply_to" not in payload  # absent unless RESEND_REPLY_TO is set


@respx.mock
def test_resend_attachment_content_is_base64_of_source_bytes(monkeypatch, tmp_path):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_notreal")
    monkeypatch.setenv("RESEND_FROM_EMAIL", "hire@catalist.dev")
    route = respx.post("https://api.resend.com/emails").mock(
        return_value=httpx.Response(200, json={"id": "re_att"})
    )
    pdf_bytes = b"%PDF-1.4\nfake brief bytes \x00\x01\x02 end"
    brief = tmp_path / "assignment_brief.pdf"
    brief.write_bytes(pdf_bytes)
    msg = EmailMessage(
        to="a@b.com",
        subject="s",
        html_body="<p>x</p>",
        attachments=[EmailAttachment(filename="assignment_brief.pdf", path=str(brief))],
    )

    result = ResendEmailSender().send(msg)
    assert result.success

    attachments = _sent_payload(route)["attachments"]
    assert len(attachments) == 1
    assert attachments[0]["filename"] == "assignment_brief.pdf"
    # content is a base64 STRING that decodes back to the exact source PDF bytes.
    decoded = base64.b64decode(attachments[0]["content"])
    assert decoded == pdf_bytes


@respx.mock
def test_resend_reply_to_present_only_when_set(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_notreal")
    monkeypatch.setenv("RESEND_FROM_EMAIL", "hire@catalist.dev")
    monkeypatch.setenv("RESEND_REPLY_TO", "talent@catalist.dev")
    route = respx.post("https://api.resend.com/emails").mock(
        return_value=httpx.Response(200, json={"id": "re_reply"})
    )
    msg = EmailMessage(to="a@b.com", subject="s", html_body="<p>x</p>")
    ResendEmailSender().send(msg)
    assert _sent_payload(route)["reply_to"] == "talent@catalist.dev"


@respx.mock
def test_resend_send_api_error_is_wrapped_not_raised(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_notreal")
    monkeypatch.setenv("RESEND_FROM_EMAIL", "hire@catalist.dev")
    respx.post("https://api.resend.com/emails").mock(
        return_value=httpx.Response(422, text="invalid recipient")
    )
    msg = EmailMessage(to="bad", subject="s", html_body="<p>x</p>")
    result = ResendEmailSender().send(msg)
    assert result.success is False
    # Resend's status + message are surfaced in the typed failure.
    assert "422" in (result.error or "")
    assert "invalid recipient" in (result.error or "")


# --------------------------------------------------------------------------- #
# API: POST /candidates/{id}/send-assignment
# --------------------------------------------------------------------------- #
@pytest.fixture
def store_path(tmp_path, monkeypatch):
    path = tmp_path / "candidates.json"
    monkeypatch.setenv("CATALIST_CANDIDATE_STORE_PATH", str(path))
    monkeypatch.setenv("CATALIST_JOB_STORE_PATH", str(tmp_path / "jobs.json"))
    monkeypatch.delenv("EMAIL_MODE", raising=False)  # default mock
    # A job with an uploaded brief so shortlisted sends can succeed.
    JSONJobRepository(path=tmp_path / "jobs.json").add(
        Job(
            id=JOB_ID,
            title="Role",
            job_description="jd",
            rubric=Rubric(job_title="Role", criteria=[{"name": "c", "weight": 1.0}]),
        )
    )
    provision_brief(JOB_ID)
    return path


def _seed(store_path: Path, status: CandidateStatus, cid: str = "c1") -> str:
    store = JSONCandidateStore(path=store_path)
    cand = Candidate(
        id=cid,
        name="Alice",
        email="alice@example.com",
        cv_filename=f"{cid}.pdf",
        file_hash=f"hash-{cid}",
        job_id=JOB_ID,
        status=status,
    )
    store.upsert(cand, None, None)
    return cid


def test_send_assignment_happy_path(store_path, monkeypatch):
    monkeypatch.setenv("ASSIGNMENT_DEADLINE_DAYS", "7")
    cid = _seed(store_path, CandidateStatus.shortlisted)

    resp = client.post(f"/candidates/{cid}/send-assignment")
    assert resp.status_code == 200
    cand = resp.json()["candidate"]
    assert cand["status"] == "assignment_sent"
    assert cand["assignment_sent_count"] == 1
    assert cand["assignment_sent_at"] is not None
    assert cand["assignment_deadline"] == (date.today() + timedelta(days=7)).isoformat()

    # Outbox file written with the right recipient / subject / attachment.
    files = list((settings.data_dir / "outbox").glob(f"{cid}_*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    assert data["to"] == "alice@example.com"
    assert "assignment" in data["subject"].lower()
    assert data["attachments"] == ["assignment_brief.pdf"]


def test_send_assignment_404_unknown(store_path):
    resp = client.post("/candidates/ghost/send-assignment")
    assert resp.status_code == 404


def test_send_assignment_409_when_not_shortlisted(store_path):
    cid = _seed(store_path, CandidateStatus.scored)
    resp = client.post(f"/candidates/{cid}/send-assignment")
    assert resp.status_code == 409
    # Status unchanged.
    assert JSONCandidateStore(path=store_path).get(cid).candidate.status is CandidateStatus.scored


def test_second_send_without_force_is_409(store_path):
    cid = _seed(store_path, CandidateStatus.shortlisted)
    assert client.post(f"/candidates/{cid}/send-assignment").status_code == 200
    # Now assignment_sent -> a plain resend is blocked.
    resp = client.post(f"/candidates/{cid}/send-assignment")
    assert resp.status_code == 409


def test_force_resend_increments_count(store_path):
    cid = _seed(store_path, CandidateStatus.shortlisted)
    assert client.post(f"/candidates/{cid}/send-assignment").status_code == 200

    resp = client.post(f"/candidates/{cid}/send-assignment", json={"force": True})
    assert resp.status_code == 200
    assert resp.json()["candidate"]["assignment_sent_count"] == 2
    # Two outbox files now exist for this candidate.
    files = list((settings.data_dir / "outbox").glob(f"{cid}_*.json"))
    assert len(files) == 2


def test_send_failure_surfaces_502_and_leaves_status(store_path, monkeypatch):
    cid = _seed(store_path, CandidateStatus.shortlisted)

    class _FailingSender:
        name = "failing"

        def send(self, message):
            return EmailSendResult(success=False, error="simulated provider outage")

    monkeypatch.setattr("app.api.routes.get_email_sender", lambda: _FailingSender())

    resp = client.post(f"/candidates/{cid}/send-assignment")
    assert resp.status_code == 502
    assert "simulated provider outage" in resp.json()["detail"]
    # Status NOT advanced — still shortlisted, count still 0.
    record = JSONCandidateStore(path=store_path).get(cid)
    assert record.candidate.status is CandidateStatus.shortlisted
    assert record.candidate.assignment_sent_count == 0
