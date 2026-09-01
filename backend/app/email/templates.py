"""Assignment email content."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

from app.email.base import EmailAttachment, EmailMessage
from app.models import Candidate

DEFAULT_BRIEF_FILENAME = "assignment_brief.pdf"
DEFAULT_SENDER_NAME = "The Catalist Media Team"
SUBMISSION_EMAIL = "wanna.work@catalist.media"
CONTACT_PHONE = "+94 774990833"


def _ordinal_date(d: date) -> str:
    """Format a date as e.g. '5th July 2026'."""
    n = d.day
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix} {d.strftime('%B %Y')}"


def render_assignment_email(
    candidate: Candidate,
    job_title: str,
    deadline: date,
    brief_path: str | Path,
    *,
    brief_filename: str = DEFAULT_BRIEF_FILENAME,
    sender_name: str = DEFAULT_SENDER_NAME,
    custom_message: Optional[str] = None,
) -> EmailMessage:
    """Build the assignment email (subject + HTML body + the job's brief).

    Uses Catalist Media's standard assignment wording; ``sender_name`` (the full
    name of the reviewer who sent it) is rendered in the signature. The brief
    attachment comes from ``brief_path`` (the job's uploaded brief).
    ``custom_message``, if given, is added as an extra line.
    """
    deadline_str = _ordinal_date(deadline)
    role = job_title or "the role"

    extra = (
        f"  <p>{custom_message}</p>\n" if custom_message and custom_message.strip() else ""
    )

    subject = f"Your Catalist Media assignment for {role}"
    html_body = f"""\
<div style="font-family: Arial, Helvetica, sans-serif; font-size: 15px; color: #1a1a1a; line-height: 1.6;">
  <p>Hi,</p>
  <p>Thank you for applying to Catalist Media!</p>
  <p>Herewith, I have attached the assignment.</p>
{extra}  <p>Submission deadline: <strong>{deadline_str}</strong></p>
  <p>
    Once you&rsquo;ve completed the assignment, please email it to
    <a href="mailto:{SUBMISSION_EMAIL}">{SUBMISSION_EMAIL}</a> on or before the deadline.
  </p>
  <p>
    We look forward to hearing from you. If you have any questions please feel
    free to reply to this email or contact me via {CONTACT_PHONE}.
  </p>
  <p>Best regards,<br/>{sender_name}<br/>Catalist Media</p>
</div>"""

    attachments = [EmailAttachment(filename=brief_filename, path=str(brief_path))]

    return EmailMessage(
        to=candidate.email or "",
        to_name=candidate.name,
        subject=subject,
        html_body=html_body,
        attachments=attachments,
        metadata={"candidate_id": candidate.id},
    )
