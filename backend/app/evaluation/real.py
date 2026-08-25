"""Real vision+text evaluator backed by OpenRouter (OpenAI-compatible API).

This is the Phase 2 drop-in behind the ``Evaluator`` protocol. Nothing upstream
(parsing, API, models) changes to use it.

Provider swappability: everything OpenRouter-specific lives in this file. To hit
a different OpenAI-compatible endpoint (or Anthropic's API directly), change the
request building here only — the interface, prompts, image prep, and callers are
untouched.
"""
from __future__ import annotations

import json
import time
from typing import Any

import httpx

from app.config import (
    get_openrouter_api_key,
    get_openrouter_model,
    settings,
)
from app.evaluation._response import build_evaluation
from app.evaluation.errors import EvaluationError, EvaluatorConfigError
from app.evaluation.images import encode_image_data_url
from app.evaluation.prompts import (
    build_retry_message,
    build_system_prompt,
    build_user_text,
)
from app.models import Evaluation, ParsedCV, Rubric

# httpx status codes we treat as transient and worth a network retry.
_RETRYABLE_STATUS = {500, 502, 503, 504, 429}


class OpenRouterEvaluator:
    """Scores a CV with a vision+text model via OpenRouter's chat completions."""

    name = "openrouter"

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        model: str | None = None,
    ) -> None:
        # Allow injection for tests; otherwise built lazily at call time.
        self._injected_client = client
        self._model_override = model

    # -- public API -------------------------------------------------------- #
    def evaluate(
        self,
        parsed_cv: ParsedCV,
        job_description: str,
        rubric: Rubric,
        *,
        pdf_bytes: bytes | None = None,  # noqa: ARG002 - pdf_direct is anthropic-only
    ) -> Evaluation:
        api_key = get_openrouter_api_key()
        if not api_key:
            raise EvaluatorConfigError(
                "OPENROUTER_API_KEY is not set. Set it in the environment to use "
                "the OpenRouter evaluator (EVALUATOR_MODE=openrouter), or use the mock."
            )

        model = self._model_override or get_openrouter_model()
        messages = self._build_messages(parsed_cv, job_description, rubric)

        # First attempt.
        content = self._call_model(messages, api_key=api_key, model=model)
        try:
            return self._parse_evaluation(content, parsed_cv, rubric)
        except (json.JSONDecodeError, ValueError) as first_error:
            # Single corrective JSON-retry: tell the model exactly what broke.
            messages.append({"role": "assistant", "content": content})
            messages.append(
                {"role": "user", "content": build_retry_message(str(first_error))}
            )
            retry_content = self._call_model(messages, api_key=api_key, model=model)
            try:
                return self._parse_evaluation(retry_content, parsed_cv, rubric)
            except (json.JSONDecodeError, ValueError) as second_error:
                raise EvaluationError(
                    "Model did not return a valid Evaluation after one retry. "
                    f"First error: {first_error}. Second error: {second_error}."
                ) from second_error

    # -- message building -------------------------------------------------- #
    def _build_messages(
        self,
        parsed_cv: ParsedCV,
        job_description: str,
        rubric: Rubric,
    ) -> list[dict[str, Any]]:
        system_prompt = build_system_prompt(job_description, rubric)
        include_images = rubric.requires_visual_review

        user_content: list[dict[str, Any]] = [
            {"type": "text", "text": build_user_text(parsed_cv.raw_text, include_images)}
        ]
        # Images are attached ONLY when the rubric asks for visual review — this
        # is the actual cost/latency saving for content-only rubrics.
        if include_images:
            for page_image in parsed_cv.page_images[: settings.max_eval_pages]:
                try:
                    data_url = encode_image_data_url(page_image.image_path)
                except (FileNotFoundError, OSError):
                    # A missing/broken image shouldn't kill the whole evaluation;
                    # the text plus remaining images still carry signal.
                    continue
                user_content.append(
                    {"type": "image_url", "image_url": {"url": data_url}}
                )

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

    # -- HTTP -------------------------------------------------------------- #
    def _call_model(
        self,
        messages: list[dict[str, Any]],
        *,
        api_key: str,
        model: str,
    ) -> str:
        url = f"{settings.openrouter_api_base}/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # Optional OpenRouter attribution headers.
            "HTTP-Referer": "https://catalist.internal/recruit-screening",
            "X-Title": "Catalist Recruit Screening",
        }

        data = self._post_with_retries(url, payload, headers)
        return self._extract_content(data)

    def _post_with_retries(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        attempts = max(1, settings.eval_max_network_attempts)
        last_exc: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                client = self._injected_client or httpx.Client(
                    timeout=settings.eval_request_timeout_s
                )
                try:
                    response = client.post(url, json=payload, headers=headers)
                finally:
                    if self._injected_client is None:
                        client.close()

                if response.status_code in _RETRYABLE_STATUS:
                    last_exc = EvaluationError(
                        f"OpenRouter returned {response.status_code}: "
                        f"{response.text[:300]}"
                    )
                    self._maybe_backoff(attempt, attempts)
                    continue

                if response.status_code >= 400:
                    # Non-retryable client error (bad key, bad request, etc.).
                    raise EvaluationError(
                        f"OpenRouter request failed with "
                        f"{response.status_code}: {response.text[:300]}"
                    )

                return response.json()

            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                self._maybe_backoff(attempt, attempts)

        raise EvaluationError(
            f"OpenRouter request failed after {attempts} attempt(s): {last_exc}"
        ) from last_exc

    @staticmethod
    def _maybe_backoff(attempt: int, attempts: int) -> None:
        if attempt < attempts:
            time.sleep(settings.eval_network_backoff_s * attempt)

    # -- response parsing -------------------------------------------------- #
    @staticmethod
    def _extract_content(data: dict[str, Any]) -> str:
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise EvaluationError(
                f"Unexpected OpenRouter response shape: {json.dumps(data)[:300]}"
            ) from exc

    def _parse_evaluation(
        self,
        content: str,
        parsed_cv: ParsedCV,
        rubric: Rubric,
    ) -> Evaluation:
        return build_evaluation(
            content,
            candidate_id=parsed_cv.candidate_id,
            rubric=rubric,
            evaluated_by=f"{self.name}:{self._model_override or get_openrouter_model()}",
        )
