"""Tests for intake sources and the intake factory (fully offline)."""
from __future__ import annotations

import pytest

from app.intake import (
    GoogleFormsIntakeSource,
    IntakeConfigError,
    LocalFixtureIntakeSource,
    get_intake_source,
)
from app.intake.google_forms import GoogleFormsIntakeSource as GFS


# --------------------------------------------------------------------------- #
# Local fixture source
# --------------------------------------------------------------------------- #
def test_local_fixture_reads_all_submissions():
    subs = LocalFixtureIntakeSource().fetch_new_submissions()
    assert len(subs) == 5  # 3 backend-engineer + 2 graphic-designer
    emails = {s.email for s in subs}
    assert "jane.doe@example.com" in emails
    assert all(s.cv_file_ref.endswith(".pdf") for s in subs)


def test_local_fixture_filters_by_job_id():
    source = LocalFixtureIntakeSource()
    backend = source.fetch_new_submissions("backend-engineer")
    design = source.fetch_new_submissions("graphic-designer")
    assert len(backend) == 3
    assert len(design) == 2
    assert all(s.job_id == "backend-engineer" for s in backend)
    assert all(s.job_id == "graphic-designer" for s in design)
    assert {s.email for s in design} == {
        "dana.lee@example.com",
        "miguel.torres@example.com",
    }


def test_local_fixture_download_copies_file(tmp_path):
    source = LocalFixtureIntakeSource()
    sub = source.fetch_new_submissions()[0]
    dest = source.download_cv(sub, tmp_path)
    assert dest.exists()
    assert dest.parent == tmp_path
    assert dest.read_bytes()[:5] == b"%PDF-"


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #
def test_factory_defaults_to_local(monkeypatch):
    monkeypatch.delenv("INTAKE_MODE", raising=False)
    assert isinstance(get_intake_source(), LocalFixtureIntakeSource)


def test_factory_returns_google_when_mode_google(monkeypatch):
    monkeypatch.setenv("INTAKE_MODE", "google")
    assert isinstance(get_intake_source(), GoogleFormsIntakeSource)


# --------------------------------------------------------------------------- #
# Google source: constructible with zero env vars, errors only on call
# --------------------------------------------------------------------------- #
def test_google_source_constructs_without_env(monkeypatch):
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)
    # Must not raise.
    source = GoogleFormsIntakeSource()
    assert source.name == "google_forms"


def test_google_fetch_without_sheet_id_raises_config_error(monkeypatch):
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", "/tmp/whatever.json")
    with pytest.raises(IntakeConfigError):
        GoogleFormsIntakeSource().fetch_new_submissions()


def test_google_fetch_without_service_account_raises_config_error(monkeypatch):
    monkeypatch.setenv("GOOGLE_SHEET_ID", "sheet-123")
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)
    with pytest.raises(IntakeConfigError):
        GoogleFormsIntakeSource().fetch_new_submissions()


@pytest.mark.parametrize(
    "cell,expected",
    [
        ("https://drive.google.com/open?id=ABC123def456", "ABC123def456"),
        ("https://drive.google.com/file/d/XYZ789ghijk/view?usp=sharing", "XYZ789ghijk"),
        ("ABC123def456ghi", "ABC123def456ghi"),
        ("", ""),
        ("not a link", ""),
    ],
)
def test_drive_id_extraction(cell, expected):
    assert GFS._extract_drive_id(cell) == expected
