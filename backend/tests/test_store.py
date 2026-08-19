"""Tests for the JSON candidate store (dedup, ordering, atomic writes)."""
from __future__ import annotations

import json

import pytest

from app.models import Candidate, CandidateStatus, Evaluation, Recommendation
from app.store import JSONCandidateStore


def _candidate(cid: str, file_hash: str, name: str) -> Candidate:
    return Candidate(id=cid, name=name, cv_filename=f"{cid}.pdf", file_hash=file_hash)


def _evaluation(cid: str, score: float) -> Evaluation:
    return Evaluation(
        candidate_id=cid,
        criterion_scores=[],
        overall_score=score,
        recommendation=Recommendation.borderline,
        summary="s",
        evaluated_by="mock",
    )


@pytest.fixture
def store(tmp_path):
    return JSONCandidateStore(path=tmp_path / "candidates.json")


def test_upsert_and_get_by_file_hash(store):
    c = _candidate("id1", "hashAAA", "Alice")
    store.upsert(c, None, _evaluation("id1", 70))

    found = store.get_by_file_hash("hashAAA")
    assert found is not None and found.id == "id1"
    assert store.get_by_file_hash("nope") is None


def test_upsert_replaces_same_id(store):
    store.upsert(_candidate("id1", "h1", "Alice"), None, _evaluation("id1", 50))
    store.upsert(_candidate("id1", "h1", "Alice v2"), None, _evaluation("id1", 90))
    records = store.list_all()
    assert len(records) == 1
    assert records[0].candidate.name == "Alice v2"
    assert records[0].overall_score == 90


def test_list_all_and_ordering_key(store):
    store.upsert(_candidate("a", "ha", "A"), None, _evaluation("a", 40))
    store.upsert(_candidate("b", "hb", "B"), None, _evaluation("b", 88))
    store.upsert(_candidate("c", "hc", "C"), None, _evaluation("c", 65))
    ranked = sorted(store.list_all(), key=lambda r: r.overall_score, reverse=True)
    assert [r.candidate.id for r in ranked] == ["b", "c", "a"]


def test_update_status(store):
    store.upsert(_candidate("id1", "h1", "Alice"), None, _evaluation("id1", 50))
    store.update_status("id1", CandidateStatus.shortlisted)
    assert store.list_all()[0].candidate.status is CandidateStatus.shortlisted
    with pytest.raises(KeyError):
        store.update_status("missing", CandidateStatus.rejected)


def test_clean_write_leaves_valid_file_and_no_temp(store, tmp_path):
    store.upsert(_candidate("id1", "h1", "Alice"), None, _evaluation("id1", 50))
    # File is valid JSON.
    data = json.loads(store.path.read_text())
    assert data["candidates"][0]["candidate"]["id"] == "id1"
    # No leftover temp files.
    leftovers = list(tmp_path.glob(".candidates-*.tmp"))
    assert leftovers == []


def test_interrupted_write_preserves_original(store, tmp_path, monkeypatch):
    # Seed a good file first.
    store.upsert(_candidate("id1", "h1", "Alice"), None, _evaluation("id1", 50))
    original = store.path.read_text()

    # Simulate a crash during the atomic replace step.
    import app.store.json_store as js

    def boom(*_a, **_k):
        raise OSError("simulated crash during replace")

    monkeypatch.setattr(js.os, "replace", boom)
    with pytest.raises(OSError):
        store.upsert(_candidate("id2", "h2", "Bob"), None, _evaluation("id2", 99))

    # Original file untouched, still valid, no temp leftovers.
    assert store.path.read_text() == original
    assert list(tmp_path.glob(".candidates-*.tmp")) == []
