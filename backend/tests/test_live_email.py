"""Opt-in LIVE email smoke test — sends exactly ONE real email via Resend.

Skipped by default. The normal offline suite (test_email.py) covers the payload
shape and failure handling with respx stubs and never goes near the network.

Run it deliberately (spends quota, delivers a real email):

    RUN_LIVE_EMAIL=1 \
    RESEND_API_KEY=re_... \
    RESEND_TEST_RECIPIENT=you@example.com \
    pytest -k live_email

``RESEND_FROM_EMAIL`` defaults to ``onboarding@resend.dev`` if unset. Note that
without a verified domain, Resend only delivers from ``onboarding@resend.dev`` to
your own Resend-account email address — see the README "Sending real email
(Resend)" section.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

import pytest

from app.config import settings
from app.email import ResendEmailSender, render_assignment_email
from app.models import Candidate


@pytest.mark.skipif(
    not os.getenv("RUN_LIVE_EMAIL"),
    reason="live email — opt-in, sends a real email (set RUN_LIVE_EMAIL=1)",
)
def test_live_email_sends_one_real_assignment(monkeypatch):
    recipient = os.getenv("RESEND_TEST_RECIPIENT")
    if not recipient:
        pytest.skip("set RESEND_TEST_RECIPIENT to the address that should receive the email")
    if not os.getenv("RESEND_API_KEY"):
        pytest.skip("set RESEND_API_KEY (a real Resend key) to send a live email")

    # Default the from-address to Resend's shared sender when none is configured.
    if not os.getenv("RESEND_FROM_EMAIL"):
        monkeypatch.setenv("RESEND_FROM_EMAIL", "onboarding@resend.dev")

    brief = settings.sample_data_dir / "assignment_brief.pdf"
    assert brief.exists(), "sample assignment_brief.pdf is required for the attachment"

    candidate = Candidate(
        id="live-smoke",
        name="Live Smoke Test",
        email=recipient,
        cv_filename="live.pdf",
        file_hash="live",
    )
    message = render_assignment_email(
        candidate,
        job_title="Catalist Live Email Smoke Test",
        deadline=date.today() + timedelta(days=5),
        brief_path=brief,
        custom_message="This is the Phase 11 live email smoke test — safe to ignore.",
    )

    result = ResendEmailSender().send(message)

    assert result.success, f"live send failed: {result.error}"
    assert result.provider_message_id, "Resend did not return a message id"
    print(f"\nLive email sent to {recipient} — Resend id: {result.provider_message_id}")
