"""Opt-in LIVE smoke test — costs real Anthropic API credits.

Skipped by default. It is NOT part of normal `pytest` runs and must never be
run automatically. To run it manually (spends money):

    RUN_LIVE_SMOKE=1 pytest -k live_smoke

It evaluates exactly ONE candidate (the smallest sample CV) with a text-only
rubric (requires_visual_review=false, so no image payload) using the cheapest
model, and asserts a schema-valid Evaluation comes back. Requires a real
ANTHROPIC_API_KEY in the environment (e.g. loaded from .env).
"""
from __future__ import annotations

import os

import pytest

from app.config import settings
from app.evaluation import AnthropicEvaluator
from app.models import Evaluation, Rubric
from app.parsing import parse_cv_file

# Cheapest model — sufficient to prove the wire format works.
LIVE_SMOKE_MODEL = "claude-haiku-4-5-20251001"


@pytest.mark.skipif(
    not os.getenv("RUN_LIVE_SMOKE"),
    reason="live smoke test — opt-in only, costs real API credits",
)
def test_live_smoke_anthropic_single_candidate(tmp_path):
    assert os.getenv("ANTHROPIC_API_KEY"), "Set ANTHROPIC_API_KEY to run the live smoke test."

    # Smallest sample CV (single page, text-based).
    cv_path = settings.sample_data_dir / "sample_cv_text_2.pdf"
    _candidate, parsed = parse_cv_file(cv_path, output_root=tmp_path / "out")

    rubric = Rubric.model_validate_json(
        (settings.sample_data_dir / "rubric.json").read_text()
    )
    assert rubric.requires_visual_review is False  # text-only: no image payload

    evaluator = AnthropicEvaluator(model=LIVE_SMOKE_MODEL)
    evaluation = evaluator.evaluate(parsed, "Backend engineer role.", rubric)

    assert isinstance(evaluation, Evaluation)
    assert 0 <= evaluation.overall_score <= 100
    assert len(evaluation.criterion_scores) == len(rubric.criteria)
    assert evaluation.evaluated_by == f"anthropic:{LIVE_SMOKE_MODEL}"
