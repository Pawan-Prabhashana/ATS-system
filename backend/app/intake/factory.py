"""Intake-source factory: selects the implementation from INTAKE_MODE."""
from __future__ import annotations

from app.config import get_intake_mode
from app.intake.base import IntakeSource
from app.intake.google_forms import GoogleFormsIntakeSource
from app.intake.local_fixture import LocalFixtureIntakeSource


def get_intake_source() -> IntakeSource:
    """Return the configured intake source.

    ``INTAKE_MODE=google`` -> :class:`GoogleFormsIntakeSource`; anything else
    (default ``local``) -> :class:`LocalFixtureIntakeSource`. Read at call time.
    """
    if get_intake_mode() == "google":
        return GoogleFormsIntakeSource()
    return LocalFixtureIntakeSource()
