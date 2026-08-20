"""Phase 7B: per-job Google Forms binding + test-intake (offline, stubbed)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.intake.errors import IntakeConfigError
from app.intake.google_forms import GoogleFormsIntakeSource
from app.main import app

client = TestClient(app)


# --------------------------------------------------------------------------- #
# Fake Google Sheets client (records the spreadsheetId it was asked for)
# --------------------------------------------------------------------------- #
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


GOOD_ROWS = [
    ["Timestamp", "Name", "Email", "CV Upload"],
    ["2026-01-01", "Bob", "bob@x.com", "https://drive.google.com/open?id=ABC123def456"],
    ["2026-01-02", "Cara", "cara@x.com", "https://drive.google.com/file/d/XYZ789ghijk/view"],
]


# --------------------------------------------------------------------------- #
# Source binds to ITS OWN sheet, not the env
# --------------------------------------------------------------------------- #
def test_source_reads_its_own_sheet_not_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_SHEET_ID", "ENV-SHEET")  # must be ignored
    captured: dict = {}
    monkeypatch.setattr(
        GoogleFormsIntakeSource,
        "_build_clients",
        lambda self: (_fake_sheets(GOOD_ROWS, captured), object()),
    )

    src = GoogleFormsIntakeSource(sheet_id="SHEET-A")
    subs = src.fetch_new_submissions("job-a")

    assert captured["sheet_id"] == "SHEET-A"  # bound to the job's sheet, not env
    assert len(subs) == 2
    assert all(s.job_id == "job-a" for s in subs)  # rows tagged with the job
    assert subs[0].cv_file_ref == "ABC123def456"
    assert subs[1].cv_file_ref == "XYZ789ghijk"
    assert subs[0].email == "bob@x.com"


# --------------------------------------------------------------------------- #
# test-intake endpoint
# --------------------------------------------------------------------------- #
@pytest.fixture
def job_store(tmp_path, monkeypatch):
    monkeypatch.setenv("CATALIST_JOB_STORE_PATH", str(tmp_path / "jobs.json"))


def _make_job(google_sheet_id=None) -> str:
    body = {
        "title": "Role",
        "job_description": "jd",
        "rubric": {"job_title": "X", "criteria": [{"name": "c", "weight": 1.0}]},
    }
    if google_sheet_id is not None:
        body["google_sheet_id"] = google_sheet_id
    return client.post("/jobs", json=body).json()["id"]


def test_test_intake_connected_true(job_store, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        GoogleFormsIntakeSource,
        "_build_clients",
        lambda self: (_fake_sheets(GOOD_ROWS, captured), object()),
    )
    jid = _make_job(google_sheet_id="SHEET-A")

    resp = client.post(f"/jobs/{jid}/test-intake")
    assert resp.status_code == 200
    b = resp.json()
    assert b["connected"] is True
    assert b["row_count"] == 2  # excludes header
    assert b["detected_columns"]["email"] == "Email"
    assert b["detected_columns"]["cv"] == "CV Upload"
    assert b["error"] is None
    assert captured["sheet_id"] == "SHEET-A"


def test_test_intake_reports_failure_never_500(job_store, monkeypatch):
    def boom(self):
        raise IntakeConfigError("Sheet not shared with the service account.")

    monkeypatch.setattr(GoogleFormsIntakeSource, "_build_clients", boom)
    jid = _make_job(google_sheet_id="SHEET-A")

    resp = client.post(f"/jobs/{jid}/test-intake")
    assert resp.status_code == 200  # NOT a 500
    b = resp.json()
    assert b["connected"] is False
    assert "not shared" in b["error"].lower()


def test_test_intake_no_sheet_configured(job_store):
    jid = _make_job(google_sheet_id=None)
    resp = client.post(f"/jobs/{jid}/test-intake")
    assert resp.status_code == 200
    b = resp.json()
    assert b["connected"] is False
    assert "no google sheet" in b["error"].lower()


def test_test_intake_unknown_job_404(job_store):
    assert client.post("/jobs/nope/test-intake").status_code == 404


def test_ingest_google_read_failure_is_502_not_500(job_store, tmp_path, monkeypatch):
    # A Google-connected job whose Sheet read fails (API disabled, not shared…)
    # must surface a clean, actionable error, never a raw 500.
    monkeypatch.setenv("CATALIST_CANDIDATE_STORE_PATH", str(tmp_path / "candidates.json"))

    def boom(self):
        raise IntakeConfigError("Google Sheets API is disabled for this project.")

    monkeypatch.setattr(GoogleFormsIntakeSource, "_build_clients", boom)
    jid = _make_job(google_sheet_id="SHEET-A")

    resp = client.post(f"/jobs/{jid}/ingest")
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
