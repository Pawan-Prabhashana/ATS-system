"""Shared response parsing for LLM-backed evaluators.

Both ``OpenRouterEvaluator`` and ``AnthropicEvaluator`` receive a text blob that
must contain a JSON object matching the ``Evaluation`` schema. The extraction +
validation is identical regardless of which SDK produced the text, so it lives
here to avoid drift between the two evaluators.
"""
from __future__ import annotations

import json

from app.models import Evaluation, Rubric


def extract_json_object(content: str) -> str:
    """Pull the JSON object out of a model message.

    Handles clean JSON, and defensively strips ```json fences / surrounding
    prose by taking the outermost ``{...}`` span. Raises ``ValueError`` if no
    object-looking span is present.
    """
    if content is None:
        raise ValueError("Model returned empty content.")
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"No JSON object found in model output: {text[:200]!r}")
    return text[start : end + 1]


def build_evaluation(
    content: str,
    *,
    candidate_id: str,
    rubric: Rubric,
    evaluated_by: str,
) -> Evaluation:
    """Parse + validate a model response into an :class:`Evaluation`.

    May raise ``json.JSONDecodeError`` (bad JSON) or ``ValueError`` (schema
    validation / criteria-name mismatch); callers treat both as "retry-able".
    """
    raw = extract_json_object(content)
    data = json.loads(raw)  # json.JSONDecodeError on malformed JSON

    # Force our own identity fields regardless of what the model echoed.
    data["candidate_id"] = candidate_id
    data["evaluated_by"] = evaluated_by

    # pydantic ValidationError is a subclass of ValueError.
    evaluation = Evaluation.model_validate(data)

    # Guard: exactly one score per rubric criterion, names matching.
    expected = [c.name for c in rubric.criteria]
    got = [cs.criterion_name for cs in evaluation.criterion_scores]
    if sorted(got) != sorted(expected):
        raise ValueError(
            f"criterion_scores names {got} do not match rubric {expected}"
        )
    return evaluation
