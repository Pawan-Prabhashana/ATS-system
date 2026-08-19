"""Tests for the evaluator factory and config-driven mode selection."""
from __future__ import annotations

from app.evaluation import (
    AnthropicEvaluator,
    MockEvaluator,
    OpenRouterEvaluator,
    get_evaluator,
)


def test_factory_defaults_to_mock(monkeypatch):
    monkeypatch.delenv("EVALUATOR_MODE", raising=False)
    assert isinstance(get_evaluator(), MockEvaluator)


def test_factory_returns_openrouter_when_mode_openrouter(monkeypatch):
    monkeypatch.setenv("EVALUATOR_MODE", "openrouter")
    assert isinstance(get_evaluator(), OpenRouterEvaluator)


def test_factory_returns_anthropic_when_mode_anthropic(monkeypatch):
    monkeypatch.setenv("EVALUATOR_MODE", "anthropic")
    assert isinstance(get_evaluator(), AnthropicEvaluator)


def test_factory_mode_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("EVALUATOR_MODE", "Anthropic")
    assert isinstance(get_evaluator(), AnthropicEvaluator)


def test_factory_unknown_mode_falls_back_to_mock(monkeypatch):
    monkeypatch.setenv("EVALUATOR_MODE", "banana")
    assert isinstance(get_evaluator(), MockEvaluator)


def test_factory_legacy_real_is_no_longer_openrouter(monkeypatch):
    # 'real' was renamed to 'openrouter'; the old value now falls back to mock.
    monkeypatch.setenv("EVALUATOR_MODE", "real")
    assert isinstance(get_evaluator(), MockEvaluator)
