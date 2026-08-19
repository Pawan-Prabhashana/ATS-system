"""Evaluator factory: selects the implementation from EVALUATOR_MODE."""
from __future__ import annotations

from app.config import get_evaluator_mode
from app.evaluation.anthropic_native import AnthropicEvaluator
from app.evaluation.base import Evaluator
from app.evaluation.mock import MockEvaluator
from app.evaluation.real import OpenRouterEvaluator


def get_evaluator() -> Evaluator:
    """Return the configured evaluator.

    ``EVALUATOR_MODE``:
      - ``openrouter`` -> :class:`OpenRouterEvaluator` (OpenAI-compatible API)
      - ``anthropic``  -> :class:`AnthropicEvaluator` (native Anthropic SDK)
      - anything else (default ``mock``) -> :class:`MockEvaluator`

    Read at call time so flipping the env var takes effect without re-importing.
    """
    mode = get_evaluator_mode()
    if mode == "openrouter":
        return OpenRouterEvaluator()
    if mode == "anthropic":
        return AnthropicEvaluator()
    return MockEvaluator()
