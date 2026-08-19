"""Tests for AnthropicEvaluator — offline via respx (the SDK is built on httpx).

No real ANTHROPIC_API_KEY and no network are required.
"""
from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.evaluation import AnthropicEvaluator, EvaluationError, EvaluatorConfigError
from app.models import Evaluation, PageImage, ParsedCV

MESSAGES_URL = "https://api.anthropic.com/v1/messages"


@pytest.fixture
def parsed_cv() -> ParsedCV:
    return ParsedCV(
        candidate_id="cand-A",
        raw_text="Jane Doe. 6 years Python, FastAPI, pytest.",
        page_count=1,
    )


def _cv_with_pages(tmp_path, n=5) -> ParsedCV:
    from PIL import Image

    page_images = []
    for i in range(1, n + 1):
        p = tmp_path / f"page_{i}.png"
        Image.new("RGB", (600, 800), (240, 240, 240)).save(p, "PNG")
        page_images.append(PageImage(page_number=i, image_path=str(p), width=600, height=800))
    return ParsedCV(candidate_id="cand-img", raw_text="text", page_count=n, page_images=page_images)


def _valid_eval_json(rubric) -> str:
    scores = [
        {"criterion_name": c.name, "score": 80.0, "weight": c.weight, "evidence": f"e {c.name}"}
        for c in rubric.criteria
    ]
    total = sum(c.weight for c in rubric.criteria)
    overall = round(sum(s["score"] * s["weight"] for s in scores) / total, 1)
    return json.dumps(
        {
            "criterion_scores": scores,
            "overall_score": overall,
            "recommendation": "shortlist",
            "summary": "Strong.",
        }
    )


def _message_response(text: str, status: int = 200) -> httpx.Response:
    if status != 200:
        return httpx.Response(status, json={"type": "error", "error": {"type": "x", "message": "boom"}})
    return httpx.Response(
        200,
        json={
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": "claude-haiku-4-5-20251001",
            "content": [{"type": "text", "text": text}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 20},
        },
    )


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr("app.config.settings.eval_network_backoff_s", 0.0)


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)


# --------------------------------------------------------------------------- #
# Config / key handling
# --------------------------------------------------------------------------- #
def test_construct_without_key_does_not_raise(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    AnthropicEvaluator()  # must not raise


def test_missing_api_key_raises_config_error_at_call_time(monkeypatch, parsed_cv, rubric):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(EvaluatorConfigError):
        AnthropicEvaluator().evaluate(parsed_cv, "jd", rubric)


# --------------------------------------------------------------------------- #
# Happy path + native shape
# --------------------------------------------------------------------------- #
@respx.mock
def test_valid_response_parses(with_key, parsed_cv, rubric):
    captured = {}

    def _cap(request):
        captured["body"] = json.loads(request.content)
        return _message_response(_valid_eval_json(rubric))

    route = respx.post(MESSAGES_URL).mock(side_effect=_cap)
    ev = AnthropicEvaluator().evaluate(parsed_cv, "jd", rubric)

    assert route.call_count == 1
    assert "temperature" not in captured["body"]
    assert isinstance(ev, Evaluation)
    assert ev.candidate_id == "cand-A"
    assert ev.evaluated_by.startswith("anthropic:")
    assert len(ev.criterion_scores) == len(rubric.criteria)
    Evaluation.model_validate(ev.model_dump())


@respx.mock
def test_model_env_var_is_used(monkeypatch, with_key, parsed_cv, rubric):
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    captured = {}

    def _cap(request):
        captured["model"] = json.loads(request.content)["model"]
        return _message_response(_valid_eval_json(rubric))

    respx.post(MESSAGES_URL).mock(side_effect=_cap)
    ev = AnthropicEvaluator().evaluate(parsed_cv, "jd", rubric)
    assert captured["model"] == "claude-haiku-4-5-20251001"
    assert ev.evaluated_by == "anthropic:claude-haiku-4-5-20251001"


# --------------------------------------------------------------------------- #
# Conditional vision: native image blocks present/absent by rubric
# --------------------------------------------------------------------------- #
def _capture(rubric):
    captured = {}

    def cb(request):
        body = json.loads(request.content)
        content = body["messages"][0]["content"]
        captured["images"] = [b for b in content if b.get("type") == "image"]
        captured["texts"] = [b for b in content if b.get("type") == "text"]
        captured["system"] = body.get("system", "")
        return _message_response(_valid_eval_json(rubric))

    return captured, cb


@respx.mock
def test_visual_rubric_sends_native_image_blocks(with_key, tmp_path, design_rubric):
    cv = _cv_with_pages(tmp_path, n=5)
    captured, cb = _capture(design_rubric)
    respx.post(MESSAGES_URL).mock(side_effect=cb)

    AnthropicEvaluator().evaluate(cv, "jd", design_rubric)

    assert len(captured["images"]) == 3  # capped at MAX_EVAL_PAGES
    # Native Anthropic shape, NOT OpenAI's image_url.
    src = captured["images"][0]["source"]
    assert src["type"] == "base64"
    assert src["media_type"] == "image/jpeg"
    assert src["data"]
    assert "visual hierarchy" in captured["system"].lower()


@respx.mock
def test_text_only_rubric_sends_no_image_blocks(with_key, tmp_path, rubric):
    cv = _cv_with_pages(tmp_path, n=5)  # images available but rubric is content-only
    captured, cb = _capture(rubric)
    respx.post(MESSAGES_URL).mock(side_effect=cb)

    AnthropicEvaluator().evaluate(cv, "jd", rubric)

    assert captured["images"] == []  # no image payload at all
    assert len(captured["texts"]) == 1
    assert "visual hierarchy" not in captured["system"].lower()


# --------------------------------------------------------------------------- #
# JSON retry + network retry
# --------------------------------------------------------------------------- #
@respx.mock
def test_malformed_then_valid_retries_once(with_key, parsed_cv, rubric):
    responses = [
        _message_response("not json at all"),
        _message_response(_valid_eval_json(rubric)),
    ]
    route = respx.post(MESSAGES_URL).mock(side_effect=responses)
    ev = AnthropicEvaluator().evaluate(parsed_cv, "jd", rubric)
    assert route.call_count == 2
    assert isinstance(ev, Evaluation)


@respx.mock
def test_twice_malformed_raises_evaluation_error(with_key, parsed_cv, rubric):
    responses = [_message_response("nope"), _message_response("still nope")]
    route = respx.post(MESSAGES_URL).mock(side_effect=responses)
    with pytest.raises(EvaluationError):
        AnthropicEvaluator().evaluate(parsed_cv, "jd", rubric)
    assert route.call_count == 2


@respx.mock
def test_retries_on_5xx_then_succeeds(with_key, parsed_cv, rubric):
    responses = [
        _message_response("", status=503),
        _message_response(_valid_eval_json(rubric)),
    ]
    route = respx.post(MESSAGES_URL).mock(side_effect=responses)
    ev = AnthropicEvaluator().evaluate(parsed_cv, "jd", rubric)
    assert route.call_count == 2
    assert isinstance(ev, Evaluation)


@respx.mock
def test_timeout_exhausts_attempts_and_raises(with_key, parsed_cv, rubric):
    route = respx.post(MESSAGES_URL).mock(side_effect=httpx.TimeoutException("timed out"))
    with pytest.raises(EvaluationError):
        AnthropicEvaluator().evaluate(parsed_cv, "jd", rubric)
    assert route.call_count == 2  # EVAL_MAX_NETWORK_ATTEMPTS default


@respx.mock
def test_4xx_is_not_retried(with_key, parsed_cv, rubric):
    route = respx.post(MESSAGES_URL).mock(return_value=_message_response("", status=401))
    with pytest.raises(EvaluationError):
        AnthropicEvaluator().evaluate(parsed_cv, "jd", rubric)
    assert route.call_count == 1
