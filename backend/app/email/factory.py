"""Email-sender factory: selects the implementation from EMAIL_MODE."""
from __future__ import annotations

from app.config import get_email_mode
from app.email.base import EmailSender
from app.email.mock_sender import MockEmailSender
from app.email.resend_sender import ResendEmailSender


def get_email_sender() -> EmailSender:
    """Return the configured email sender.

    ``EMAIL_MODE=resend`` -> :class:`ResendEmailSender`; anything else (default
    ``mock``) -> :class:`MockEmailSender`. Read at call time.
    """
    if get_email_mode() == "resend":
        return ResendEmailSender()
    return MockEmailSender()
