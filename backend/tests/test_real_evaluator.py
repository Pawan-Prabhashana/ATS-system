"""Tests for OpenRouterEvaluator — fully offline via respx (no real key/network)."""
from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.evaluation import EvaluationError, EvaluatorConfigError, OpenRouterEvaluator
from app.models import Evaluation, ParsedCV

COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"


@pytest.fixture
def parsed_cv() -> ParsedCV:
    # No page_images -> no filesystem/image encoding needed for these tests.
    return ParsedCV(
        candidate_id="cand-123",
        raw_text="Jane Doe. 6 years Python, FastAPI, pytest, PDF pipelines.",
        page_count=1,
    )


def _valid_eval_json(rubric) -> str:
    """A schema-valid model 'content' string for the given rubric."""
    criterion_scores = [
        {
            "criterion_name": c.name,
            "score": 80.0,
            "weight": c.weight,
            "evidence": f"Evidence for {c.name}.",
        }
        for c in rubric.criteria
    ]
    total_w = sum(c.weight for c in rubric.criteria)
    overall = round(sum(cs["score"] * cs["weight"] for cs in criterion_scores) / total_w, 1)
    return json.dumps(
        {
            "criterion_scores": criterion_scores,
            "overall_score": overall,
            "recommendation": "shortlist",
            "summary": "Strong candidate.",
        }
    )


def _completion_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"role": "assistant", "content": content}}]},
    )


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    # Keep network-retry tests instant.
    monkeypatch.setattr("app.config.settings.eval_network_backoff_s", 0.0)


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)


# --------------------------------------------------------------------------- #
# Config / key handling
# --------------------------------------------------------------------------- #
def test_missing_api_key_raises_config_error_at_call_time(monkeypatch, parsed_cv, rubric):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    # Construction must NOT raise (no key needed at import/instantiation).
    evaluator = OpenRouterEvaluator()
    with pytest.raises(EvaluatorConfigError):
        evaluator.evaluate(parsed_cv, "job description", rubric)


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #
@respx.mock
def test_valid_response_parses_into_evaluation(with_key, parsed_cv, rubric):
    route = respx.post(COMPLETIONS_URL).mock(
        return_value=_completion_response(_valid_eval_json(rubric))
    )
    ev = OpenRouterEvaluator().evaluate(parsed_cv, "job description", rubric)

    assert route.call_count == 1
    assert isinstance(ev, Evaluation)
    assert ev.candidate_id == "cand-123"
    assert ev.evaluated_by.startswith("openrouter:")
    assert len(ev.criterion_scores) == len(rubric.criteria)
    assert ev.recommendation.value == "shortlist"
    # Round-trips through schema validation.
    Evaluation.model_validate(ev.model_dump())


@respx.mock
def test_model_env_var_is_used(monkeypatch, with_key, parsed_cv, rubric):
    monkeypatch.setenv("OPENROUTER_MODEL", "openai/gpt-4o")
    captured = {}

    def _capture(request):
        captured["model"] = json.loads(request.content)["model"]
        return _completion_response(_valid_eval_json(rubric))

    respx.post(COMPLETIONS_URL).mock(side_effect=_capture)
    ev = OpenRouterEvaluator().evaluate(parsed_cv, "jd", rubric)
    assert captured["model"] == "openai/gpt-4o"
    assert ev.evaluated_by == "openrouter:openai/gpt-4o"


# --------------------------------------------------------------------------- #
# JSON-retry logic
# --------------------------------------------------------------------------- #
@respx.mock
def test_malformed_then_valid_retries_once(with_key, parsed_cv, rubric):
    responses = [
        _completion_response("this is not json at all"),
        _completion_response(_valid_eval_json(rubric)),
    ]
    route = respx.post(COMPLETIONS_URL).mock(side_effect=responses)

    ev = OpenRouterEvaluator().evaluate(parsed_cv, "jd", rubric)
    assert route.call_count == 2  # initial + one corrective retry
    assert isinstance(ev, Evaluation)
    assert ev.candidate_id == "cand-123"


@respx.mock
def test_twice_malformed_raises_evaluation_error(with_key, parsed_cv, rubric):
    responses = [
        _completion_response("nope, not json"),
        _completion_response("still not json"),
    ]
    route = respx.post(COMPLETIONS_URL).mock(side_effect=responses)

    with pytest.raises(EvaluationError):
        OpenRouterEvaluator().evaluate(parsed_cv, "jd", rubric)
    assert route.call_count == 2  # tried once, retried once, then gave up


@respx.mock
def test_valid_json_wrong_criteria_triggers_retry(with_key, parsed_cv, rubric):
    # Valid JSON + schema, but criterion names don't match the rubric -> retry.
    bad = json.dumps(
        {
            "criterion_scores": [
                {"criterion_name": "Made up", "score": 50, "weight": 1, "evidence": "x"}
            ],
            "overall_score": 50,
            "recommendation": "borderline",
            "summary": "s",
        }
    )
    responses = [
        _completion_response(bad),
        _completion_response(_valid_eval_json(rubric)),
    ]
    route = respx.post(COMPLETIONS_URL).mock(side_effect=responses)
    ev = OpenRouterEvaluator().evaluate(parsed_cv, "jd", rubric)
    assert route.call_count == 2
    assert len(ev.criterion_scores) == len(rubric.criteria)


@respx.mock
def test_fenced_json_is_tolerated(with_key, parsed_cv, rubric):
    fenced = "```json\n" + _valid_eval_json(rubric) + "\n```"
    respx.post(COMPLETIONS_URL).mock(return_value=_completion_response(fenced))
    ev = OpenRouterEvaluator().evaluate(parsed_cv, "jd", rubric)
    assert isinstance(ev, Evaluation)


# --------------------------------------------------------------------------- #
# Network retry logic (separate from JSON retry)
# --------------------------------------------------------------------------- #
@respx.mock
def test_retries_on_5xx_then_succeeds(with_key, parsed_cv, rubric):
    responses = [
        httpx.Response(503, text="upstream unavailable"),
        _completion_response(_valid_eval_json(rubric)),
    ]
    route = respx.post(COMPLETIONS_URL).mock(side_effect=responses)
    ev = OpenRouterEvaluator().evaluate(parsed_cv, "jd", rubric)
    assert route.call_count == 2
    assert isinstance(ev, Evaluation)


@respx.mock
def test_timeout_exhausts_attempts_and_raises(with_key, parsed_cv, rubric):
    route = respx.post(COMPLETIONS_URL).mock(
        side_effect=httpx.TimeoutException("timed out")
    )
    with pytest.raises(EvaluationError):
        OpenRouterEvaluator().evaluate(parsed_cv, "jd", rubric)
    # Default EVAL_MAX_NETWORK_ATTEMPTS = 2.
    assert route.call_count == 2


@respx.mock
def test_4xx_is_not_retried(with_key, parsed_cv, rubric):
    route = respx.post(COMPLETIONS_URL).mock(
        return_value=httpx.Response(401, text="invalid api key")
    )
    with pytest.raises(EvaluationError):
        OpenRouterEvaluator().evaluate(parsed_cv, "jd", rubric)
    assert route.call_count == 1  # client error -> no retry


# --------------------------------------------------------------------------- #
# Conditional vision: images only when the rubric requires visual review
# --------------------------------------------------------------------------- #
def _cv_with_pages(tmp_path, n=5):
    from PIL import Image

    from app.models import PageImage

    page_images = []
    for i in range(1, n + 1):
        p = tmp_path / f"page_{i}.png"
        Image.new("RGB", (600, 800), (240, 240, 240)).save(p, "PNG")
        page_images.append(PageImage(page_number=i, image_path=str(p), width=600, height=800))
    return ParsedCV(
        candidate_id="c-img", raw_text="text", page_count=n, page_images=page_images
    )


def _capture_user_content(rubric):
    captured = {}

    def _capture(request):
        body = json.loads(request.content)
        user_msg = body["messages"][1]["content"]
        captured["image_blocks"] = [b for b in user_msg if b["type"] == "image_url"]
        captured["text_blocks"] = [b for b in user_msg if b["type"] == "text"]
        return _completion_response(_valid_eval_json(rubric))

    return captured, _capture


@respx.mock
def test_visual_rubric_includes_images_capped_at_max(with_key, tmp_path, design_rubric):
    cv = _cv_with_pages(tmp_path, n=5)
    captured, cb = _capture_user_content(design_rubric)
    respx.post(COMPLETIONS_URL).mock(side_effect=cb)

    OpenRouterEvaluator().evaluate(cv, "jd", design_rubric)

    assert len(captured["image_blocks"]) == 3  # capped at MAX_EVAL_PAGES
    assert len(captured["text_blocks"]) == 1
    assert captured["image_blocks"][0]["image_url"]["url"].startswith(
        "data:image/jpeg;base64,"
    )


@respx.mock
def test_text_only_rubric_sends_no_images(with_key, tmp_path, rubric):
    # Same CV WITH page images available, but a content-only rubric.
    cv = _cv_with_pages(tmp_path, n=5)
    captured, cb = _capture_user_content(rubric)
    respx.post(COMPLETIONS_URL).mock(side_effect=cb)

    OpenRouterEvaluator().evaluate(cv, "jd", rubric)

    assert captured["image_blocks"] == []  # no image payload at all
    assert len(captured["text_blocks"]) == 1
