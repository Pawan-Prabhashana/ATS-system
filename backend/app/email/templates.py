"""Assignment email content."""
from __future__ import annotations

from datetime import date

from app.config import settings
from app.email.base import EmailAttachment, EmailMessage
from app.models import Candidate

ASSIGNMENT_BRIEF_FILENAME = "assignment_brief.pdf"


def render_assignment_email(
    candidate: Candidate,
    job_title: str,
    deadline: date,
) -> EmailMessage:
    """Build the assignment email (subject + HTML body + brief attachment)."""
    name = candidate.name or "there"
    deadline_str = deadline.strftime("%A, %d %B %Y")
    role = job_title or "the role"

    subject = f"Your Catalist assignment for {role}"
    html_body = f"""\
<div style="font-family: Arial, Helvetica, sans-serif; font-size: 15px; color: #1a1a1a; line-height: 1.6;">
  <p>Hi {name},</p>
  <p>
    Thank you for applying for <strong>{role}</strong>. As the next step in our
    process, we'd like you to complete a short assignment.
  </p>
  <p>
    The brief is attached as a PDF. Please read it carefully and submit your
    response by <strong>{deadline_str}</strong>. If anything is unclear, just
    reply to this email and we'll be happy to help.
  </p>
  <p>We're looking forward to seeing your work.</p>
  <p>Best regards,<br/>The Catalist Hiring Team</p>
</div>"""

    brief_path = settings.sample_data_dir / ASSIGNMENT_BRIEF_FILENAME
    attachments = [
        EmailAttachment(filename=ASSIGNMENT_BRIEF_FILENAME, path=str(brief_path))
    ]

    return EmailMessage(
        to=candidate.email or "",
        to_name=candidate.name,
        subject=subject,
        html_body=html_body,
        attachments=attachments,
        metadata={"candidate_id": candidate.id},
    )
