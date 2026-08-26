"""Phase 16: pdf_direct scoring path + PDF viewer endpoint (offline, stubbed)."""
from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.evaluation.anthropic_native import AnthropicEvaluator
from app.main import app
from app.models import (
    CriterionScore,
    Evaluation,
    Job,
    PageImage,
    ParsedCV,
    Recommendation,
    Rubric,
)
from app.pipeline import run_site_ingestion
from app.store import JSONCandidateStore, JSONJobRepository, seed_jobs

client = TestClient(app)


def _rubric(visual: bool = False) -> Rubric:
    return Rubric(job_title="X", criteria=[{"name": "c", "weight": 1.0}], requires_visual_review=visual)


# --------------------------------------------------------------------------- #
# Evaluator: document block (pdf_direct) vs image blocks (render)
# --------------------------------------------------------------------------- #
def test_pdf_direct_attaches_document_and_no_images():
    parsed = ParsedCV(candidate_id="c", raw_text="hi", page_images=[])
    _system, content = AnthropicEvaluator()._build_content(
        parsed, "jd", _rubric(visual=True), pdf_bytes=b"%PDF-1.4 fake cv bytes"
    )
    types = [b["type"] for b in content]
    assert "document" in types
    assert "image" not in types  # no rendered images in pdf_direct

    doc = next(b for b in content if b["type"] == "document")
    assert doc["source"]["type"] == "base64"
    assert doc["source"]["media_type"] == "application/pdf"
    assert base64.b64decode(doc["source"]["data"]) == b"%PDF-1.4 fake cv bytes"


def test_render_mode_attaches_images_and_no_document(tmp_path):
    img = tmp_path / "page_1.png"
    Image.new("RGB", (12, 16), "white").save(img)
    parsed = ParsedCV(
        candidate_id="c",
        raw_text="hi",
        page_images=[PageImage(page_number=1, image_path=str(img), width=12, height=16)],
    )
    _system, content = AnthropicEvaluator()._build_content(parsed, "jd", _rubric(visual=True))  # no pdf_bytes
    types = [b["type"] for b in content]
    assert "document" not in types
    assert "image" in types


# --------------------------------------------------------------------------- #
# Ingestion in pdf_direct: no rendering, no page images, PDF bytes to evaluator
# --------------------------------------------------------------------------- #
class _FakeAnthropic:
    """Stand-in anthropic evaluator: records the pdf_bytes it was handed."""

    name = "anthropic"

    def __init__(self) -> None:
        self.pdf_calls: list[bytes | None] = []

    def evaluate(self, parsed_cv, job_description, rubric, *, pdf_bytes=None):
        self.pdf_calls.append(pdf_bytes)
        return Evaluation(
            candidate_id=parsed_cv.candidate_id,
            criterion_scores=[CriterionScore(criterion_name="c", score=60.0, weight=1.0, evidence="e")],
            overall_score=60.0,
            recommendation=Recommendation.borderline,
            summary="s",
            evaluated_by="anthropic:test",
        )


def test_pdf_direct_ingestion_skips_renderer_and_stores_no_images(tmp_path, monkeypatch):
    monkeypatch.setenv("CV_MODE", "pdf_direct")
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path / "data")

    # If the renderer is called in pdf_direct, fail loudly.
    def boom(*_a, **_k):
        raise AssertionError("render_pages must NOT be called in pdf_direct mode")

    monkeypatch.setattr("app.parsing.orchestrator.render_pages", boom)

    store = JSONCandidateStore(path=tmp_path / "candidates.json")
    fake = _FakeAnthropic()
    jobs = [Job(id="backend-engineer", title="Backend Engineer", role_key="Backend Engineer", job_description="jd", rubric=_rubric())]

    summary = run_site_ingestion(jobs, store=store, evaluator=fake)

    assert summary.processed == 3  # Backend Engineer x3 from the fixture
    # The evaluator received real PDF bytes (not None) each time.
    assert all(isinstance(b, bytes) and b[:5] == b"%PDF-" for b in fake.pdf_calls)
    # No page images stored; the CV PDF still persisted for the viewer.
    for rec in store.list_all():
        assert rec.page_image_files == []
        assert rec.cv_file == "cv.pdf"


def test_pdf_direct_without_anthropic_is_clean_config_error(tmp_path, monkeypatch):
    monkeypatch.setenv("CV_MODE", "pdf_direct")
    monkeypatch.setenv("CATALIST_JOB_STORE_PATH", str(tmp_path / "jobs.json"))
    monkeypatch.setenv("CATALIST_CANDIDATE_STORE_PATH", str(tmp_path / "candidates.json"))
    monkeypatch.delenv("EVALUATOR_MODE", raising=False)  # -> mock, not anthropic
    monkeypatch.delenv("INTAKE_MODE", raising=False)
    seed_jobs(JSONJobRepository(path=tmp_path / "jobs.json"))

    resp = client.post("/ingest")
    assert resp.status_code == 400  # clean config error, not a 500
    assert "pdf_direct" in resp.json()["detail"]
    assert "anthropic" in resp.json()["detail"].lower()


def test_default_cv_mode_is_pdf_direct(monkeypatch):
    """Phase 17: pdf_direct is the default; render is opt-in via CV_MODE=render."""
    from app.config import get_cv_mode

    monkeypatch.delenv("CV_MODE", raising=False)  # unset -> default
    assert get_cv_mode() == "pdf_direct"
    monkeypatch.setenv("CV_MODE", "render")
    assert get_cv_mode() == "render"


def test_default_unset_without_anthropic_is_clean_config_error(tmp_path, monkeypatch):
    """With CV_MODE UNSET (so the pdf_direct default applies) and a non-anthropic
    evaluator, ingestion must fail with a clear, actionable 400 — not a 500/crash
    — naming both fixes (EVALUATOR_MODE=anthropic or CV_MODE=render)."""
    monkeypatch.delenv("CV_MODE", raising=False)  # unset -> pdf_direct default
    monkeypatch.setenv("CATALIST_JOB_STORE_PATH", str(tmp_path / "jobs.json"))
    monkeypatch.setenv("CATALIST_CANDIDATE_STORE_PATH", str(tmp_path / "candidates.json"))
    monkeypatch.delenv("EVALUATOR_MODE", raising=False)  # -> mock, not anthropic
    monkeypatch.delenv("INTAKE_MODE", raising=False)
    seed_jobs(JSONJobRepository(path=tmp_path / "jobs.json"))

    resp = client.post("/ingest")
    assert resp.status_code == 400  # clean config error, not a 500
    detail = resp.json()["detail"].lower()
    assert "anthropic" in detail and "render" in detail


# --------------------------------------------------------------------------- #
# GET /candidates/{id}/cv
# --------------------------------------------------------------------------- #
@pytest.fixture
def ingested(tmp_path, monkeypatch):
    """Render-mode ingest via the API so a candidate with a local cv.pdf exists."""
    monkeypatch.setenv("CATALIST_JOB_STORE_PATH", str(tmp_path / "jobs.json"))
    monkeypatch.setenv("CATALIST_CANDIDATE_STORE_PATH", str(tmp_path / "candidates.json"))
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path / "data")
    monkeypatch.delenv("EVALUATOR_MODE", raising=False)
    monkeypatch.delenv("INTAKE_MODE", raising=False)
    # This fixture exercises the RENDER path with the mock evaluator (it needs a
    # local cv.pdf + page images). pdf_direct is now the default, so pin render
    # explicitly rather than relying on the default.
    monkeypatch.setenv("CV_MODE", "render")
    seed_jobs(JSONJobRepository(path=tmp_path / "jobs.json"))
    assert client.post("/ingest").status_code == 200
    return client.get("/candidates").json()


def test_cv_endpoint_streams_local_pdf(ingested):
    cid = ingested[0]["candidate"]["id"]
    resp = client.get(f"/candidates/{cid}/cv")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content[:5] == b"%PDF-"


def test_cv_endpoint_exposed_in_detail(ingested):
    cid = ingested[0]["candidate"]["id"]
    detail = client.get(f"/candidates/{cid}").json()
    assert detail["cv_pdf_url"] == f"/candidates/{cid}/cv"


def test_cv_endpoint_404_when_unknown(ingested):
    assert client.get("/candidates/ghost/cv").status_code == 404


def test_cv_endpoint_drive_branch(tmp_path, monkeypatch):
    """A candidate with a cv_drive_file_id streams bytes fetched via Drive (stubbed)."""
    monkeypatch.setenv("CATALIST_CANDIDATE_STORE_PATH", str(tmp_path / "candidates.json"))
    from app.intake.google_forms import GoogleFormsIntakeSource
    from app.models import Candidate

    monkeypatch.setattr(GoogleFormsIntakeSource, "download_cv_bytes", lambda self, fid: b"%PDF-1.4 from-drive")

    store = JSONCandidateStore(path=tmp_path / "candidates.json")
    store.upsert(
        Candidate(id="drv1", job_id="j", cv_filename="x.pdf", file_hash="h", cv_drive_file_id="DRIVE-ABC"),
        None,
        None,
    )
    resp = client.get("/candidates/drv1/cv")
    assert resp.status_code == 200
    assert resp.content == b"%PDF-1.4 from-drive"


@pytest.mark.real_auth
def test_cv_endpoint_requires_auth(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("APP_AUTH_USERNAME", "admin")
    monkeypatch.setenv("APP_AUTH_PASSWORD", "pw")
    monkeypatch.setenv("AUTH_SECRET_KEY", "unit-test-secret-key-at-least-32-bytes-long")
    assert client.get("/candidates/anything/cv").status_code == 401
