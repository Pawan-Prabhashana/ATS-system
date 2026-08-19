"""Deterministic mock evaluator — no network, no API keys.

Scores are derived deterministically from the candidate's ``file_hash`` (via the
``candidate_id`` and criterion name), so tests are stable across runs while
still producing varied, well-formed output.
"""
from __future__ import annotations

import hashlib

from app.models import (
    CriterionScore,
    Evaluation,
    ParsedCV,
    Recommendation,
    Rubric,
)


class MockEvaluator:
    """A stand-in :class:`~app.evaluation.base.Evaluator` for Phase 1."""

    name = "mock"

    def _seed_score(self, seed: str) -> float:
        """Map an arbitrary seed string to a deterministic 0-100 score."""
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        # Use 4 hex chars -> 0..65535 -> scale to 0..100, rounded to 1 dp.
        return round(int(digest[:4], 16) / 0xFFFF * 100, 1)

    def evaluate(
        self,
        parsed_cv: ParsedCV,
        job_description: str,  # noqa: ARG002 - part of the interface contract
        rubric: Rubric,
    ) -> Evaluation:
        criterion_scores: list[CriterionScore] = []
        weighted_sum = 0.0
        total_weight = 0.0

        for criterion in rubric.criteria:
            score = self._seed_score(f"{parsed_cv.candidate_id}:{criterion.name}")
            criterion_scores.append(
                CriterionScore(
                    criterion_name=criterion.name,
                    score=score,
                    weight=criterion.weight,
                    evidence=self._evidence(parsed_cv, criterion.name),
                )
            )
            weighted_sum += score * criterion.weight
            total_weight += criterion.weight

        overall = round(weighted_sum / total_weight, 1) if total_weight else 0.0

        if overall >= 70:
            recommendation = Recommendation.shortlist
        elif overall >= 50:
            recommendation = Recommendation.borderline
        else:
            recommendation = Recommendation.reject

        return Evaluation(
            candidate_id=parsed_cv.candidate_id,
            criterion_scores=criterion_scores,
            overall_score=overall,
            recommendation=recommendation,
            summary=(
                f"[MOCK] Deterministic evaluation across {len(criterion_scores)} "
                f"criteria. Overall {overall}/100 -> {recommendation.value}. "
                "Replace with a real vision+text evaluator in Phase 2."
            ),
            evaluated_by=self.name,
        )

    @staticmethod
    def _evidence(parsed_cv: ParsedCV, criterion_name: str) -> str:
        """Produce plausible evidence text from the CV's extracted text."""
        snippet = " ".join(parsed_cv.raw_text.split())[:120]
        if not snippet:
            return (
                f"[MOCK] No extractable text for '{criterion_name}'; "
                "would defer to page images in a real evaluator."
            )
        return f"[MOCK] Based on CV text near: \"{snippet}…\""
