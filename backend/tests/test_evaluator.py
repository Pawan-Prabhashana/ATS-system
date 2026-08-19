"""Tests for the mock evaluator and its interface conformance."""
from __future__ import annotations

from pathlib import Path

from app.evaluation import Evaluator, MockEvaluator
from app.models import Evaluation, ParsedCV, Recommendation
from app.parsing import parse_cv_file


def _valid_evaluation(ev: Evaluation, rubric) -> None:
    assert isinstance(ev, Evaluation)
    assert 0 <= ev.overall_score <= 100
    assert ev.recommendation in set(Recommendation)
    assert ev.evaluated_by == "mock"
    assert len(ev.criterion_scores) == len(rubric.criteria)
    for cs in ev.criterion_scores:
        assert 0 <= cs.score <= 100
        assert cs.weight > 0
        assert cs.evidence  # non-empty


def test_mock_is_an_evaluator():
    assert isinstance(MockEvaluator(), Evaluator)


def test_mock_returns_schema_valid_evaluation(text_cv_path: Path, output_root: Path, rubric):
    _candidate, parsed = parse_cv_file(text_cv_path, output_root=output_root)
    ev = MockEvaluator().evaluate(parsed, "job description", rubric)
    _valid_evaluation(ev, rubric)
    # Round-trips through JSON schema validation.
    Evaluation.model_validate(ev.model_dump())


def test_mock_is_deterministic(rubric):
    parsed = ParsedCV(candidate_id="fixed-id-123", raw_text="Python FastAPI pytest")
    a = MockEvaluator().evaluate(parsed, "jd", rubric)
    b = MockEvaluator().evaluate(parsed, "jd", rubric)
    assert a.model_dump() == b.model_dump()


def test_mock_handles_empty_text(rubric):
    parsed = ParsedCV(candidate_id="empty-cv", raw_text="")
    ev = MockEvaluator().evaluate(parsed, "jd", rubric)
    _valid_evaluation(ev, rubric)
