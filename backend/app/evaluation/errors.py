"""Typed errors for the evaluation layer."""
from __future__ import annotations


class EvaluatorError(Exception):
    """Base class for evaluator failures."""


class EvaluatorConfigError(EvaluatorError):
    """Raised when the evaluator is misconfigured (e.g. missing API key).

    Raised on first use, never at import time.
    """


class EvaluationError(EvaluatorError):
    """Raised when the model could not produce a valid Evaluation.

    e.g. the response failed JSON parsing/validation on both the initial attempt
    and the single corrective retry. Callers may choose to fall back to the mock
    evaluator; this class never does so silently on their behalf.
    """
