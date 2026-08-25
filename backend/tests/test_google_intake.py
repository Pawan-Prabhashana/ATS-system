"""Phase 15: single site Google Form — role-tagged rows, /intake/status, /ingest
(offline, stubbed — no real Google)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.intake.errors import IntakeConfigError
from app.intake.google_forms import GoogleFormsIntakeSource
from app.main import app

client = TestClient(app)


def _fake_sheets(values, captured):
    class _Exec:
        def __init__(self, sid):
            self._sid = sid

        def execute(self):
            captured["sheet_id"] = self._sid
            return {"values": values}

    class _Values:
        def get(self, spreadsheetId, range):  # noqa: A002 - mirror the real API
            return _Exec(spreadsheetId)

    class _Spreadsheets:
        def values(self):
            return _Values()

    class _Sheets:
        def spreadsheets(self):
            return _Spreadsheets()

    return _Sheets()


# One site form with a role question column ("Which role?" contains 'role').
GOOD_ROWS = [
    ["Timestamp", "Name", "Email", "Which role?", "CV Upload"],
    ["2026-01-01", "Bob", "bob@x.com", "Backend Engineer", "https://drive.google.com/open?id=ABC123def456"],
    ["2026-01-02", "Cara", "cara@x.com", "Graphic Design Intern", "https://drive.google.com/file/d/XYZ789ghijk/view"],
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("FORM_ROLE_COLUMN", raising=False)


# --------------------------------------------------------------------------- #
# Source reads the site sheet and tags each row with its role
# --------------------------------------------------------------------------- #
def test_source_reads_site_sheet_and_tags_role(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        GoogleFormsIntakeSource,
        "_build_clients",
        lambda self: (_fake_sheets(GOOD_ROWS, captured), object()),
    )
    subs = GoogleFormsIntakeSource(sheet_id="SHEET-A").fetch_new_submissions()

    assert captured["sheet_id"] == "SHEET-A"
    assert len(subs) == 2
    assert subs[0].role == "Backend Engineer"
    assert subs[1].role == "Graphic Design Intern"
    assert subs[0].cv_file_ref == "ABC123def456"
    assert subs[0].email == "bob@x.com"


# --------------------------------------------------------------------------- #
# /intake/status (site-level connection + role-column detection)
# --------------------------------------------------------------------------- #
def test_intake_status_google_connected(monkeypatch):
    monkeypatch.setenv("INTAKE_MODE", "google")
    monkeypatch.setenv("GOOGLE_SHEET_ID", "SHEET-A")
    monkeypatch.setattr(
        GoogleFormsIntakeSource,
        "_build_clients",
        lambda self: (_fake_sheets(GOOD_ROWS, {}), object()),
    )
    b = client.post("/intake/status").json()
    assert b["connected"] is True
    assert b["row_count"] == 2
    assert b["role_column_detected"] is True
    assert set(b["distinct_roles"]) == {"Backend Engineer", "Graphic Design Intern"}
    assert b["detected_columns"]["email"] == "Email"
    assert b["error"] is None


def test_intake_status_reports_failure_never_500(monkeypatch):
    monkeypatch.setenv("INTAKE_MODE", "google")
    monkeypatch.setenv("GOOGLE_SHEET_ID", "SHEET-A")

    def boom(self):
        raise IntakeConfigError("Sheet not shared with the service account.")

    monkeypatch.setattr(GoogleFormsIntakeSource, "_build_clients", boom)
    b = client.post("/intake/status").json()
    assert b["connected"] is False
    assert "not shared" in b["error"].lower()


def test_intake_status_no_sheet_configured(monkeypatch):
    monkeypatch.setenv("INTAKE_MODE", "google")
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
    b = client.get("/intake/status").json()
    assert b["connected"] is False
    assert "no google sheet" in b["error"].lower()


# --------------------------------------------------------------------------- #
# /ingest surfaces a Sheet read failure as a clean 502, never a raw 500
# --------------------------------------------------------------------------- #
def test_site_ingest_google_read_failure_is_502_not_500(tmp_path, monkeypatch):
    monkeypatch.setenv("INTAKE_MODE", "google")
    monkeypatch.setenv("GOOGLE_SHEET_ID", "SHEET-A")
    monkeypatch.setenv("CATALIST_JOB_STORE_PATH", str(tmp_path / "jobs.json"))
    monkeypatch.setenv("CATALIST_CANDIDATE_STORE_PATH", str(tmp_path / "candidates.json"))

    def boom(self):
        raise IntakeConfigError("Google Sheets API is disabled for this project.")

    monkeypatch.setattr(GoogleFormsIntakeSource, "_build_clients", boom)
    client.post(
        "/jobs",
        json={
            "title": "Role",
            "role_key": "Backend Engineer",
            "job_description": "jd",
            "rubric": {"job_title": "X", "criteria": [{"name": "c", "weight": 1.0}]},
        },
    )
    resp = client.post("/ingest")
    assert resp.status_code == 502
    assert "Sheets API is disabled" in resp.json()["detail"]


def test_probe_empty_sheet_is_connected_zero_rows(monkeypatch):
    monkeypatch.setattr(
        GoogleFormsIntakeSource,
        "_build_clients",
        lambda self: (_fake_sheets([], {}), object()),
    )
    result = GoogleFormsIntakeSource(sheet_id="SHEET-A").probe()
    assert result["connected"] is True
    assert result["row_count"] == 0
    assert result["role_column_detected"] is False
