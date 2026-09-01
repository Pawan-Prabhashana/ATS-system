"""Assignment-send service — shared by the single-send route and bulk send.

The per-candidate flow (status/force gating, sender call, result handling,
repository update) lives here so both endpoints run identical logic. The single
route stays a thin translator of :class:`SendOutcome` into HTTP status codes.
"""
from __future__ import annotations

import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from app.config import get_assignment_deadline_days, settings
from app.email import EmailConfigError, render_assignment_email
from app.email.factory import get_email_sender
from app.email.base import EmailSender
from app.models import CandidateStatus
from app.store.base import CandidateRepository, JobRepository
from app.store.factory import get_candidate_store, get_job_repository

BRIEF_FILENAME = "assignment_brief.pdf"


def job_brief_path(job_id: str) -> Path:
    """On-disk path to a job's uploaded assignment brief."""
    return settings.data_dir / "jobs" / job_id / BRIEF_FILENAME


class SendOutcomeStatus(str, Enum):
    sent = "sent"
    skipped_not_shortlisted = "skipped_not_shortlisted"
    skipped_already_sent = "skipped_already_sent"
    skipped_wrong_job = "skipped_wrong_job"
    no_assignment_brief = "no_assignment_brief"
    not_found = "not_found"
    failed = "failed"
    config_error = "config_error"


# How each outcome partitions in a bulk result.
_SKIP = {
    SendOutcomeStatus.skipped_not_shortlisted,
    SendOutcomeStatus.skipped_already_sent,
    SendOutcomeStatus.skipped_wrong_job,
    SendOutcomeStatus.no_assignment_brief,
}
_FAIL = {
    SendOutcomeStatus.failed,
    SendOutcomeStatus.not_found,
    SendOutcomeStatus.config_error,
}


class SendOutcome(BaseModel):
    candidate_id: str
    success: bool
    status: SendOutcomeStatus
    detail: Optional[str] = None


class BulkSendResult(BaseModel):
    job_id: str
    requested_count: int
    sent: list[SendOutcome] = Field(default_factory=list)
    skipped: list[SendOutcome] = Field(default_factory=list)
    failed: list[SendOutcome] = Field(default_factory=list)
    sent_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0


def send_assignment_to_candidate(
    candidate_id: str,
    force: bool = False,
    *,
    store: CandidateRepository | None = None,
    job_repo: JobRepository | None = None,
    sender: EmailSender | None = None,
    expected_job_id: str | None = None,
    sender_name: str | None = None,
    deadline_date: date | None = None,
) -> SendOutcome:
    """Send the assignment email to one candidate; never raises for the known
    outcomes — returns a :class:`SendOutcome` the caller maps to HTTP or a bulk
    partition.

    ``expected_job_id`` (used by bulk) flags a candidate that belongs to a
    different job as ``skipped_wrong_job`` without sending; the single-send route
    passes ``None`` so its behavior is unchanged.
    """
    store = store or get_candidate_store()

    record = store.get(candidate_id)
    if record is None:
        return SendOutcome(
            candidate_id=candidate_id,
            success=False,
            status=SendOutcomeStatus.not_found,
            detail=f"Candidate {candidate_id!r} not found.",
        )

    if expected_job_id is not None and record.candidate.job_id != expected_job_id:
        return SendOutcome(
            candidate_id=candidate_id,
            success=False,
            status=SendOutcomeStatus.skipped_wrong_job,
            detail=(
                f"Candidate belongs to job {record.candidate.job_id!r}, "
                f"not {expected_job_id!r}."
            ),
        )

    status = record.candidate.status
    resend = status is CandidateStatus.assignment_sent and force
    if status is not CandidateStatus.shortlisted and not resend:
        already = status is CandidateStatus.assignment_sent
        detail = (
            f"Cannot send assignment: candidate status is '{status.value}'. "
            "Only 'shortlisted' candidates can be sent an assignment"
            + (" (already sent — pass force=true to resend)." if already else ".")
        )
        return SendOutcome(
            candidate_id=candidate_id,
            success=False,
            status=(
                SendOutcomeStatus.skipped_already_sent
                if already
                else SendOutcomeStatus.skipped_not_shortlisted
            ),
            detail=detail,
        )

    # Resolve the job — its brief, deadline, title, and custom message drive
    # the email. Sending requires the job to have an uploaded brief.
    job_repo = job_repo or get_job_repository()
    job = job_repo.get(record.candidate.job_id) if record.candidate.job_id else None

    # Resolve the brief to a concrete file for the email attachment. Prefer the
    # local disk cache; if it was wiped (Render's ephemeral disk) fall back to the
    # DB copy, materialized to a temp file. Only "no brief at all" blocks sending.
    brief_path = job_brief_path(record.candidate.job_id) if record.candidate.job_id else None
    tmp_brief: str | None = None
    if not (job and job.assignment_brief_filename):
        return SendOutcome(
            candidate_id=candidate_id,
            success=False,
            status=SendOutcomeStatus.no_assignment_brief,
            detail="Upload an assignment brief for this job before sending.",
        )
    if not (brief_path and brief_path.exists()):
        if job.assignment_brief_data:
            fd, tmp_brief = tempfile.mkstemp(prefix="catalist-brief-", suffix=".pdf")
            with os.fdopen(fd, "wb") as fh:
                fh.write(job.assignment_brief_data)
            brief_path = Path(tmp_brief)
        else:
            return SendOutcome(
                candidate_id=candidate_id,
                success=False,
                status=SendOutcomeStatus.no_assignment_brief,
                detail="The assignment brief is missing — please re-upload it, then send.",
            )

    try:
        job_title = job.title if job else "the role"
        # Prefer an explicit deadline chosen at send time; else fall back to the
        # per-job "deadline in N days" (or the global default).
        if deadline_date is not None:
            deadline = deadline_date
        else:
            deadline_days = (
                job.assignment_deadline_days
                if job and job.assignment_deadline_days is not None
                else get_assignment_deadline_days()
            )
            deadline = date.today() + timedelta(days=deadline_days)
        sent_at = datetime.now(timezone.utc)
        render_kwargs = {
            "brief_filename": job.assignment_brief_filename or BRIEF_FILENAME,
            "custom_message": job.assignment_message if job else None,
        }
        if sender_name:
            render_kwargs["sender_name"] = sender_name
        message = render_assignment_email(record.candidate, job_title, deadline, brief_path, **render_kwargs)

        # Send. Config problems (unset creds) -> config_error; a send failure ->
        # failed, and crucially the status is NOT advanced so the reviewer can retry.
        sender = sender or get_email_sender()
        try:
            result = sender.send(message)
        except EmailConfigError as exc:
            return SendOutcome(
                candidate_id=candidate_id,
                success=False,
                status=SendOutcomeStatus.config_error,
                detail=str(exc),
            )

        if not result.success:
            return SendOutcome(
                candidate_id=candidate_id,
                success=False,
                status=SendOutcomeStatus.failed,
                detail=f"Assignment email failed to send: {result.error}",
            )

        store.record_assignment_sent(candidate_id, sent_at, deadline, sent_by=sender_name)
        return SendOutcome(
            candidate_id=candidate_id, success=True, status=SendOutcomeStatus.sent
        )
    finally:
        if tmp_brief:
            try:
                os.unlink(tmp_brief)
            except OSError:
                pass


def bulk_send_assignments(
    job_id: str,
    candidate_ids: list[str] | None = None,
    force: bool = False,
    *,
    store: CandidateRepository | None = None,
    job_repo: JobRepository | None = None,
    sender: EmailSender | None = None,
    sender_name: str | None = None,
    deadline_date: date | None = None,
) -> BulkSendResult:
    """Send assignments to many candidates in one job.

    Target selection: when ``candidate_ids`` is None, all of the job's
    ``shortlisted`` candidates; otherwise exactly the given ids (each validated
    against ``job_id``). One candidate's failure never aborts the batch.

    Callers are expected to have already verified the job exists (the route
    returns 404 for an unknown job).
    """
    store = store or get_candidate_store()
    job_repo = job_repo or get_job_repository()
    sender = sender or get_email_sender()

    if candidate_ids is None:
        targets = [
            r.candidate.id
            for r in store.list_by_job(job_id, CandidateStatus.shortlisted)
        ]
    else:
        targets = list(candidate_ids)

    result = BulkSendResult(job_id=job_id, requested_count=len(targets))

    # Deliberately SEQUENTIAL: real email providers rate-limit, and this avoids
    # bursting them. This is a conscious choice, not a missed optimization.
    for cid in targets:
        outcome = send_assignment_to_candidate(
            cid,
            force,
            store=store,
            job_repo=job_repo,
            sender=sender,
            expected_job_id=job_id,
            sender_name=sender_name,
            deadline_date=deadline_date,
        )
        if outcome.status is SendOutcomeStatus.sent:
            result.sent.append(outcome)
        elif outcome.status in _SKIP:
            result.skipped.append(outcome)
        else:  # _FAIL
            result.failed.append(outcome)

    result.sent_count = len(result.sent)
    result.skipped_count = len(result.skipped)
    result.failed_count = len(result.failed)
    return result
