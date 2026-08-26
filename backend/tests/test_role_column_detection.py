"""FORM_ROLE_COLUMN matching must tolerate the cosmetic differences that real
Google Form headers carry — trailing spaces and curly apostrophes — so the role
column is still detected (the deploy hit exactly this: a smart apostrophe in the
env value vs a straight one in the sheet header)."""
import pytest

from app.intake.base import detect_role_column

# The real sheet header: straight apostrophe + trailing space.
SHEET_HEADERS = ["Timestamp", "Job you're applying for ", "Name", "CV"]


@pytest.mark.parametrize(
    "form_role_column",
    [
        "Job you're applying for",       # straight apostrophe, no trailing space
        "Job you're applying for ",      # straight apostrophe, trailing space
        "Job you’re applying for",  # CURLY apostrophe (the deploy bug)
        "job you're applying for",       # different case
        "Job  you're   applying for",    # collapsed extra whitespace
    ],
)
def test_form_role_column_matches_despite_cosmetic_differences(monkeypatch, form_role_column):
    monkeypatch.setenv("FORM_ROLE_COLUMN", form_role_column)
    # Returns the ACTUAL sheet header (untouched), so downstream lookups work.
    assert detect_role_column(SHEET_HEADERS) == "Job you're applying for "


def test_unset_env_autodetects_applying_for_header(monkeypatch):
    # The deploy scenario: FORM_ROLE_COLUMN unset, header has no literal 'role'.
    monkeypatch.delenv("FORM_ROLE_COLUMN", raising=False)
    assert detect_role_column(SHEET_HEADERS) == "Job you're applying for "


def test_set_but_unmatched_env_falls_through_to_autodetect(monkeypatch):
    # A typo'd/stale env value must not hard-block routing — fall through.
    monkeypatch.setenv("FORM_ROLE_COLUMN", "Totally Wrong Column")
    assert detect_role_column(SHEET_HEADERS) == "Job you're applying for "


def test_returns_none_when_no_role_like_column(monkeypatch):
    monkeypatch.delenv("FORM_ROLE_COLUMN", raising=False)
    assert detect_role_column(["Timestamp", "Name", "CV"]) is None


def test_autodetect_plain_role_header(monkeypatch):
    monkeypatch.delenv("FORM_ROLE_COLUMN", raising=False)
    assert detect_role_column(["Timestamp", "Which role?", "CV"]) == "Which role?"
