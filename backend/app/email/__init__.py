"""Assignment email dispatch (mock outbox by default; Resend when configured)."""
from app.email.base import (
    EmailAttachment,
    EmailMessage,
    EmailSender,
    EmailSendResult,
)
from app.email.errors import EmailConfigError, EmailError
from app.email.factory import get_email_sender
from app.email.mock_sender import MockEmailSender
from app.email.resend_sender import ResendEmailSender
from app.email.templates import render_assignment_email

__all__ = [
    "EmailAttachment",
    "EmailMessage",
    "EmailSender",
    "EmailSendResult",
    "EmailError",
    "EmailConfigError",
    "get_email_sender",
    "MockEmailSender",
    "ResendEmailSender",
    "render_assignment_email",
]
