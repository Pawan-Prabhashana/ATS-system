"""Typed errors for the email layer."""
from __future__ import annotations


class EmailError(Exception):
    """Base class for email failures."""


class EmailConfigError(EmailError):
    """Raised when the email sender is misconfigured (e.g. missing API key).

    Raised on first use (when ``send`` is called), never at import or __init__.
    Runtime send failures (API rejects the request, invalid recipient, network)
    are NOT raised — they come back as ``EmailSendResult(success=False, ...)``.
    """
