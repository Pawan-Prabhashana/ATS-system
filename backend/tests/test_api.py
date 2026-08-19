"""Tests for the FastAPI /parse endpoint."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_parse_endpoint_returns_parsed_cv(text_cv_path: Path):
    with text_cv_path.open("rb") as fh:
        resp = client.post(
            "/parse",
            files={"file": (text_cv_path.name, fh, "application/pdf")},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["raw_text"].strip()
    assert body["page_count"] >= 1
    assert body["text_extraction_quality"] == "ok"
    assert len(body["page_images"]) == body["page_count"]


def test_parse_endpoint_rejects_non_pdf():
    resp = client.post(
        "/parse",
        files={"file": ("bogus.pdf", b"not a pdf at all", "application/pdf")},
    )
    assert resp.status_code == 400
    assert "PDF" in resp.json()["detail"]
