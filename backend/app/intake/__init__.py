"""Candidate intake sources (local fixtures + Google Forms)."""
from app.intake.base import IntakeSource, RawSubmission
from app.intake.errors import IntakeConfigError, IntakeError
from app.intake.factory import get_intake_source
from app.intake.google_forms import GoogleFormsIntakeSource
from app.intake.local_fixture import LocalFixtureIntakeSource

__all__ = [
    "IntakeSource",
    "RawSubmission",
    "IntakeError",
    "IntakeConfigError",
    "get_intake_source",
    "GoogleFormsIntakeSource",
    "LocalFixtureIntakeSource",
]
