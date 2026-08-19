"""Typed errors for the intake layer."""
from __future__ import annotations


class IntakeError(Exception):
    """Base class for intake failures."""


class IntakeConfigError(IntakeError):
    """Raised when an intake source is misconfigured.

    e.g. missing GOOGLE_SHEET_ID / GOOGLE_SERVICE_ACCOUNT_FILE, an unreadable
    credentials file, or the Google client libraries not being installed.
    Raised only when a method is actually called — never at import or __init__.
    """
