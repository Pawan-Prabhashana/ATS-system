"""Behavioral parity between the JSON and SQL (SQLite) store backends.

Every test in the ``PARITY`` group runs against BOTH backends via the
``stores`` fixture param, so the SQL implementations are proven equivalent to
the JSON ones by construction — same assertions, both stores. A few SQL-only
tests cover things the JSON store can't (DB-level UNIQUE constraint, tz-aware
reconstruction).

Fully offline: the SQL backend uses an in-memory SQLite engine (StaticPool so
the one connection is shared), never a network.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.engine import create_all
from app.models import (
    Candidate,
    CandidateStatus,
    CriterionScore,
    Evaluation,
    Job,
    JobStatus,
    Recommendation,
    Rubric,
)
from app.store.job_store import JSONJobRepository
from app.store.json_store import JSONCandidateStore
from app.store.sql_candidate_store import SQLCandidateStore
from app.store.sql_job_store import SQLJobRepository


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #
def _rubric() -> Rubric:
    return Rubric(job_title="X", criteria=[{"name": "c", "weight": 1.0}])


def _job(job_id: str = "j1", **kw) -> Job:
    return Job(id=job_id, title=kw.pop("title", "Role"), job_description="jd", rubric=_rubric(), **kw)


def _candidate(cid: str, file_hash: str, name: str, job_id: str = "") -> Candidate:
    return Candidate(id=cid, job_id=job_id, name=name, cv_filename=f"{cid}.pdf", file_hash=file_hash)


def _evaluation(cid: str, score: float) -> Evaluation:
    return Evaluation(
        candidate_id=cid,
        criterion_scores=[CriterionScore(criterion_name="c", score=score, weight=1.0, evidence="e")],
        overall_score=score,
        recommendation=Recommendation.borderline,
        summary="s",
        evaluated_by="mock",
    )


# --------------------------------------------------------------------------- #
# Backends: JSON files vs SQL-on-in-memory-SQLite. Both fresh per test.
# --------------------------------------------------------------------------- #
@pytest.fixture(params=["json", "sql"])
def stores(request, tmp_path):
    if request.param == "json":
        yield (
            JSONCandidateStore(path=tmp_path / "candidates.json"),
            JSONJobRepository(path=tmp_path / "jobs.json"),
        )
        return
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    create_all(engine)
    try:
        yield SQLCandidateStore(engine=engine), SQLJobRepository(engine=engine)
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def cand(stores):
    return stores[0]


@pytest.fixture
def jobs(stores):
    return stores[1]


# =========================================================================== #
# PARITY — jobs
# =========================================================================== #
def test_job_add_get_list(jobs):
    jobs.add(_job("a"))
    jobs.add(_job("b"))
    assert jobs.get("a").id == "a"
    assert jobs.get("missing") is None
    assert {j.id for j in jobs.list_all()} == {"a", "b"}


def test_job_duplicate_id_raises(jobs):
    jobs.add(_job("a"))
    with pytest.raises(ValueError):
        jobs.add(_job("a"))


def test_job_update_replaces(jobs):
    jobs.add(_job("a", title="Old"))
    jobs.update(_job("a", title="New"))
    assert jobs.get("a").title == "New"
    assert len(jobs.list_all()) == 1


def test_job_update_missing_raises(jobs):
    with pytest.raises(KeyError):
        jobs.update(_job("nope"))


def test_job_close_roundtrip(jobs):
    # closeJob = set status closed + update; the store persists the whole Job.
    jobs.add(_job("a"))
    j = jobs.get("a")
    closed = j.model_copy(update={"status": JobStatus.closed})
    jobs.update(closed)
    assert jobs.get("a").status.value == "closed"


def test_job_full_fields_roundtrip(jobs):
    j = _job(
        "a",
        title="Designer",
        status="open",
    ).model_copy(
        update={
            "google_sheet_id": "SHEET-1",
            "assignment_brief_filename": "brief.pdf",
            "assignment_deadline_days": 7,
            "assignment_message": "hello",
            "rubric": Rubric(
                job_title="Designer",
                criteria=[{"name": "craft", "weight": 2.0}],
                requires_visual_review=True,
            ),
        }
    )
    jobs.add(j)
    got = jobs.get("a")
    assert got.google_sheet_id == "SHEET-1"
    assert got.assignment_brief_filename == "brief.pdf"
    assert got.assignment_deadline_days == 7
    assert got.assignment_message == "hello"
    assert got.rubric.requires_visual_review is True
    # The visual-design toggle guarantees the visual criterion is present (it is
    # auto-injected at index 0), and the original "craft" criterion roundtrips.
    assert [c.name for c in got.rubric.criteria] == [c.name for c in j.rubric.criteria]
    assert got.rubric.criteria[0].name == "Visual hierarchy & layout"
    assert any(c.name == "craft" for c in got.rubric.criteria)


# =========================================================================== #
# PARITY — candidates
# =========================================================================== #
def test_decision_and_assignment_record_actor(cand):
    cand.upsert(_candidate("idA", "hA", "Alice"), None, _evaluation("idA", 70))
    # Shortlist records who decided it.
    rec = cand.update_decision("idA", "shortlist", "looks good", decided_by="Abdul Ashraff")
    assert rec.candidate.decided_by == "Abdul Ashraff"
    # Assignment send records who sent it.
    from datetime import date, datetime, timezone

    rec = cand.record_assignment_sent(
        "idA", datetime.now(timezone.utc), date(2026, 7, 5), sent_by="Mahima Passela"
    )
    assert rec.candidate.assignment_sent_by == "Mahima Passela"
    # Undo clears the decision attribution.
    rec = cand.update_decision("idA", "undecided", None)
    assert rec.candidate.decided_by is None


def test_upsert_and_get_by_job_and_hash(cand):
    cand.upsert(_candidate("id1", "hashAAA", "Alice"), None, _evaluation("id1", 70))
    found = cand.get_by_job_and_hash("", "hashAAA")
    assert found is not None and found.id == "id1"
    assert cand.get_by_job_and_hash("", "nope") is None
    # Same hash under a different job is not a match (per-job scoping).
    assert cand.get_by_job_and_hash("other-job", "hashAAA") is None


def test_get_returns_full_record(cand):
    cand.upsert(
        _candidate("id1", "h1", "Alice", job_id="j1"),
        None,
        _evaluation("id1", 70),
        artifact_dir="candidates/id1",
        cv_file="cv.pdf",
        page_image_files=["page_1.png", "page_2.png"],
    )
    rec = cand.get("id1")
    assert rec.candidate.id == "id1"
    assert rec.artifact_dir == "candidates/id1"
    assert rec.cv_file == "cv.pdf"
    assert rec.page_image_files == ["page_1.png", "page_2.png"]
    assert rec.evaluation.criterion_scores[0].criterion_name == "c"
    assert cand.get("missing") is None


def test_upsert_replaces_same_id(cand):
    cand.upsert(_candidate("id1", "h1", "Alice"), None, _evaluation("id1", 50))
    cand.upsert(_candidate("id1", "h1", "Alice v2"), None, _evaluation("id1", 90))
    records = cand.list_all()
    assert len(records) == 1
    assert records[0].candidate.name == "Alice v2"
    assert records[0].overall_score == 90


def test_list_by_job_and_status_filter(cand):
    cand.upsert(_candidate("a", "ha", "A", job_id="j1"), None, _evaluation("a", 40))
    cand.upsert(_candidate("b", "hb", "B", job_id="j1"), None, _evaluation("b", 88))
    cand.upsert(_candidate("c", "hc", "C", job_id="j2"), None, _evaluation("c", 65))
    assert {r.candidate.id for r in cand.list_by_job("j1")} == {"a", "b"}
    assert {r.candidate.id for r in cand.list_by_job("j2")} == {"c"}
    # Status filter.
    cand.update_status("b", CandidateStatus.shortlisted)
    shortlisted = cand.list_by_job("j1", status=CandidateStatus.shortlisted)
    assert [r.candidate.id for r in shortlisted] == ["b"]


def test_ordering_by_score(cand):
    cand.upsert(_candidate("a", "ha", "A"), None, _evaluation("a", 40))
    cand.upsert(_candidate("b", "hb", "B"), None, _evaluation("b", 88))
    cand.upsert(_candidate("c", "hc", "C"), None, _evaluation("c", 65))
    ranked = sorted(cand.list_all(), key=lambda r: r.overall_score, reverse=True)
    assert [r.candidate.id for r in ranked] == ["b", "c", "a"]


def test_update_status_missing_raises(cand):
    cand.upsert(_candidate("id1", "h1", "Alice"), None, _evaluation("id1", 50))
    cand.update_status("id1", CandidateStatus.shortlisted)
    assert cand.get("id1").candidate.status is CandidateStatus.shortlisted
    with pytest.raises(KeyError):
        cand.update_status("missing", CandidateStatus.rejected)


def test_decision_shortlist_and_reject(cand):
    cand.upsert(_candidate("id1", "h1", "Alice"), None, _evaluation("id1", 50))
    rec = cand.update_decision("id1", "shortlist", "great fit")
    assert rec.candidate.status is CandidateStatus.shortlisted
    assert rec.candidate.reviewer_note == "great fit"
    assert rec.candidate.decided_at is not None

    rec = cand.update_decision("id1", "reject", "not a fit")
    assert rec.candidate.status is CandidateStatus.rejected
    assert rec.candidate.reviewer_note == "not a fit"


def test_decision_undo_clears_metadata(cand):
    cand.upsert(_candidate("id1", "h1", "Alice"), None, _evaluation("id1", 50))
    cand.update_decision("id1", "shortlist", "great fit")
    rec = cand.update_decision("id1", "undecided", None)
    assert rec.candidate.status is CandidateStatus.scored
    assert rec.candidate.reviewer_note is None
    assert rec.candidate.decided_at is None


def test_decision_invalid_raises_valueerror(cand):
    cand.upsert(_candidate("id1", "h1", "Alice"), None, _evaluation("id1", 50))
    with pytest.raises(ValueError):
        cand.update_decision("id1", "banana", None)


def test_decision_invalid_beats_missing(cand):
    # An invalid decision is a ValueError even when the candidate doesn't exist
    # (validation happens before the lookup) — matches the JSON store.
    with pytest.raises(ValueError):
        cand.update_decision("missing", "banana", None)


def test_decision_missing_candidate_raises_keyerror(cand):
    with pytest.raises(KeyError):
        cand.update_decision("missing", "shortlist", None)


def test_record_assignment_sent(cand):
    cand.upsert(_candidate("id1", "h1", "Alice"), None, _evaluation("id1", 50))
    sent_at = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
    deadline = date(2026, 8, 25)
    rec = cand.record_assignment_sent("id1", sent_at, deadline)
    assert rec.candidate.status is CandidateStatus.assignment_sent
    assert rec.candidate.assignment_deadline == deadline
    assert rec.candidate.assignment_sent_count == 1
    # Second send increments the count.
    rec2 = cand.record_assignment_sent("id1", sent_at, deadline)
    assert rec2.candidate.assignment_sent_count == 2


def test_record_assignment_sent_missing_raises(cand):
    with pytest.raises(KeyError):
        cand.record_assignment_sent(
            "missing", datetime.now(timezone.utc), date.today()
        )


def test_upsert_without_evaluation(cand):
    # Parity: a candidate can be stored before scoring (evaluation is None).
    cand.upsert(_candidate("id1", "h1", "Alice"), None, None)
    rec = cand.get("id1")
    assert rec.evaluation is None
    assert rec.overall_score == -1.0


# =========================================================================== #
# SQL-ONLY — things the JSON store cannot enforce/exercise
# =========================================================================== #
@pytest.fixture
def sql_cand():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    create_all(engine)
    try:
        yield SQLCandidateStore(engine=engine)
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_unique_job_file_hash_enforced_at_db(sql_cand):
    # Two DIFFERENT ids sharing the same (job_id, file_hash) violate the UNIQUE
    # constraint. In practice the pipeline derives the id from that pair so this
    # never happens, but the DB guarantees it.
    sql_cand.upsert(_candidate("id1", "dup", "Alice", job_id="j1"), None, None)
    with pytest.raises(IntegrityError):
        sql_cand.upsert(_candidate("id2", "dup", "Bob", job_id="j1"), None, None)


def test_created_at_reconstructs_tz_aware(sql_cand):
    sql_cand.upsert(_candidate("id1", "h1", "Alice"), None, None)
    created = sql_cand.get("id1").candidate.created_at
    assert created.tzinfo is not None  # UTC, not naive
