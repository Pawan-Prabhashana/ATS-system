"""Phase 15: single-form site-level intake routed by role_key (offline).

Fixture mode (INTAKE_MODE=local) reads sample_data/mock_form_responses.csv:
  Backend Engineer x3, Graphic Design Intern x1, Motion Designer x1 (no job).
Seed jobs: backend-engineer -> "Backend Engineer", graphic-designer ->
"Graphic Design Intern".
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.store import JSONJobRepository, seed_jobs

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("CATALIST_CANDIDATE_STORE_PATH", str(tmp_path / "candidates.json"))
    monkeypatch.setenv("CATALIST_JOB_STORE_PATH", str(tmp_path / "jobs.json"))
    monkeypatch.delenv("EVALUATOR_MODE", raising=False)  # mock evaluator
    monkeypatch.delenv("INTAKE_MODE", raising=False)  # local fixture
    monkeypatch.delenv("FORM_ROLE_COLUMN", raising=False)
    seed_jobs(JSONJobRepository(path=tmp_path / "jobs.json"))


def _create_job(title, role_key, visual=False):
    body = {
        "title": title,
        "job_description": "jd for " + role_key,
        "role_key": role_key,
        "rubric": {
            "job_title": title,
            "criteria": [{"name": "c", "weight": 1.0}],
            "requires_visual_review": visual,
        },
    }
    r = client.post("/jobs", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# --------------------------------------------------------------------------- #
# Routing + held
# --------------------------------------------------------------------------- #
def test_ingest_routes_by_role_and_holds_unmatched():
    summary = client.post("/ingest").json()

    # Rows routed to the job whose role_key matches exactly.
    assert summary["processed_by_job"] == {"backend-engineer": 3, "graphic-designer": 1}
    assert summary["processed"] == 4
    # The role with no configured job is HELD, grouped by role string.
    assert summary["held_by_role"] == {"Motion Designer": 1}
    assert summary["held_total"] == 1
    assert summary["failed"] == 0

    # Held rows are NOT stored as candidates.
    assert len(client.get("/candidates").json()) == 4
    backend = client.get("/jobs/backend-engineer/candidates").json()
    design = client.get("/jobs/graphic-designer/candidates").json()
    assert len(backend) == 3 and len(design) == 1
    assert {r["candidate"]["email"] for r in design} == {"dana.lee@example.com"}


def test_held_role_flows_in_once_its_job_exists():
    first = client.post("/ingest").json()
    assert first["held_by_role"].get("Motion Designer") == 1

    # Admin sets up the previously-held role. role_key is the exact dropdown value.
    _create_job("Motion Designer", role_key="Motion Designer")

    second = client.post("/ingest").json()
    # The held applicant now processes; the already-ingested ones are dupes.
    assert second["processed_by_job"] == {"motion-designer": 1}
    assert second["skipped_duplicate"] == 4  # the 4 already stored
    assert second["held_total"] == 0

    motion = client.get("/jobs/motion-designer/candidates").json()
    assert len(motion) == 1
    assert motion[0]["candidate"]["email"] == "miguel.torres@example.com"
    assert motion[0]["evaluation"] is not None  # it was scored


def test_reingest_is_idempotent():
    client.post("/ingest")
    again = client.post("/ingest").json()
    assert again["processed"] == 0
    assert again["skipped_duplicate"] == 4
    assert again["held_by_role"] == {"Motion Designer": 1}


# --------------------------------------------------------------------------- #
# /roles
# --------------------------------------------------------------------------- #
def test_roles_lists_counts_and_has_job():
    roles = client.get("/roles").json()
    by_role = {r["role"]: r for r in roles}

    assert by_role["Backend Engineer"]["applicant_count"] == 3
    assert by_role["Backend Engineer"]["has_job"] is True
    assert by_role["Backend Engineer"]["job_id"] == "backend-engineer"

    assert by_role["Graphic Design Intern"]["applicant_count"] == 1
    assert by_role["Graphic Design Intern"]["has_job"] is True

    # A role on the form with NO configured job -> surfaced for setup.
    assert by_role["Motion Designer"]["applicant_count"] == 1
    assert by_role["Motion Designer"]["has_job"] is False
    assert by_role["Motion Designer"]["job_id"] is None


def test_roles_includes_configured_job_with_zero_applicants():
    _create_job("Data Scientist", role_key="Data Scientist")
    by_role = {r["role"]: r for r in client.get("/roles").json()}
    assert by_role["Data Scientist"]["has_job"] is True
    assert by_role["Data Scientist"]["applicant_count"] == 0


# --------------------------------------------------------------------------- #
# /intake/status
# --------------------------------------------------------------------------- #
def test_intake_status_detects_role_column():
    s = client.post("/intake/status").json()
    assert s["connected"] is True
    assert s["role_column_detected"] is True
    assert s["detected_columns"]["role"] == "role"
    assert set(s["distinct_roles"]) == {"Backend Engineer", "Graphic Design Intern", "Motion Designer"}
    assert s["error"] is None


def test_intake_status_reports_missing_role_column(monkeypatch):
    # FORM_ROLE_COLUMN pointing at a header that doesn't exist -> not detected.
    monkeypatch.setenv("FORM_ROLE_COLUMN", "Nonexistent Question")
    s = client.get("/intake/status").json()
    assert s["connected"] is True
    assert s["role_column_detected"] is False
    assert s["distinct_roles"] == []
