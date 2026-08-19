"""Evaluator boundary.

This is the seam Phase 2 plugs into: a real vision+text implementation (e.g.
Claude 3.5 Sonnet / GPT-4o via OpenRouter) implements the same ``Evaluator``
protocol and is dropped in with **no changes** to parsing or API code.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.models import Evaluation, ParsedCV, Rubric


@runtime_checkable
class Evaluator(Protocol):
    """Scores a parsed CV against a job description + rubric."""

    name: str

    def evaluate(
        self,
        parsed_cv: ParsedCV,
        job_description: str,
        rubric: Rubric,
    ) -> Evaluation:
        """Return a schema-valid :class:`Evaluation` for ``parsed_cv``."""
        ...
