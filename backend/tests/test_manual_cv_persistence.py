"""A manually-uploaded CV must survive a restart that wipes local disk: the
bytes are stored in the DB and served / used for rescore as a fallback.
"""
from fastapi.testclient import TestClient

from app.main import app
from app.models import Candidate
from app.store.base import CandidateRecord

client = TestClient(app)

PDF = b"%PDF-1.4 manual cv bytes"


def _rec() -> CandidateRecord:
    return CandidateRecord(
        candidate=Candidate(id="m1", cv_filename="alice.pdf", file_hash="h", cv_data=PDF)
    )


def test_cv_endpoint_serves_db_bytes_when_disk_gone(monkeypatch):
    class Stub:
        def get(self, cid):
            return _rec() if cid == "m1" else None

    monkeypatch.setattr("app.api.routes.get_candidate_store", lambda: Stub())
    r = client.get("/candidates/m1/cv")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content == PDF


def test_rescore_loader_falls_back_to_db_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path / "data")
    from app.pipeline.rescore import _load_cv_bytes

    assert _load_cv_bytes(_rec()) == PDF
