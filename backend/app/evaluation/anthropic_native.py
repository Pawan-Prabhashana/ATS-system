"""Native vision+text evaluator backed by Anthropic's official Python SDK.

Implements the same ``Evaluator`` protocol as ``OpenRouterEvaluator`` and reuses
the same prompts (``prompts.py``) and response parsing (``_response.py``) — the
prompt doesn't care which SDK delivers it. The only Anthropic-specific pieces
here are the message/content-block shape and the SDK call/exceptions.

Everything credential-related is lazy: importing this module and constructing
``AnthropicEvaluator()`` never require ``ANTHROPIC_API_KEY`` (or even the
``anthropic`` package) to exist — those only matter when ``evaluate()`` runs.
"""
from __future__ import annotations

import base64
import json
import threading
import time
from typing import Any, Optional

from app.config import (
    get_anthropic_api_key,
    get_anthropic_model,
    settings,
)
from app.evaluation._response import build_evaluation
from app.evaluation.errors import EvaluationError, EvaluatorConfigError
from app.evaluation.images import encode_image_anthropic_block
from app.evaluation.prompts import (
    build_retry_message,
    build_system_prompt,
    build_user_text,
)
from app.models import Evaluation, ParsedCV, Rubric

# HTTP status codes we treat as transient and worth a network retry (529 =
# Anthropic "overloaded").
_RETRYABLE_STATUS = {429, 500, 502, 503, 504, 529}


class AnthropicEvaluator:
    """Scores a CV with a Claude model via Anthropic's Messages API."""

    name = "anthropic"

    def __init__(self, *, client: Any | None = None, model: str | None = None) -> None:
        # Allow injecting a client for tests; otherwise built once and REUSED
        # across calls/threads. Building a fresh anthropic.Anthropic() per CV
        # leaks its httpx connection pool — over a long pull that piles up and
        # OOMs the instance. One shared client (httpx is thread-safe) fixes it.
        self._injected_client = client
        self._model_override = model
        self._client: Any | None = None
        self._client_lock = threading.Lock()

    def _get_client(self, api_key: str):
        if self._injected_client is not None:
            return self._injected_client
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    anthropic = _import_anthropic()
                    self._client = anthropic.Anthropic(
                        api_key=api_key,
                        timeout=settings.eval_request_timeout_s,
                        max_retries=0,  # we run our own retry loop below
                    )
        return self._client

    # -- public API -------------------------------------------------------- #
    def evaluate(
        self,
        parsed_cv: ParsedCV,
        job_description: str,
        rubric: Rubric,
        *,
        pdf_bytes: Optional[bytes] = None,
    ) -> Evaluation:
        api_key = get_anthropic_api_key()
        if not api_key:
            raise EvaluatorConfigError(
                "ANTHROPIC_API_KEY is not set. Set it in the environment to use "
                "the Anthropic evaluator (EVALUATOR_MODE=anthropic), or use the mock."
            )

        model = self._model_override or get_anthropic_model()
        system_prompt, user_content = self._build_content(
            parsed_cv, job_description, rubric, pdf_bytes=pdf_bytes
        )
        messages: list[dict[str, Any]] = [{"role": "user", "content": user_content}]

        # First attempt.
        content = self._call_model(system_prompt, messages, api_key=api_key, model=model)
        try:
            return self._parse(content, parsed_cv, rubric, model)
        except (json.JSONDecodeError, ValueError) as first_error:
            # Single corrective JSON-retry: tell the model exactly what broke.
            messages.append({"role": "assistant", "content": content})
            messages.append(
                {"role": "user", "content": build_retry_message(str(first_error))}
            )
            retry_content = self._call_model(
                system_prompt, messages, api_key=api_key, model=model
            )
            try:
                return self._parse(retry_content, parsed_cv, rubric, model)
            except (json.JSONDecodeError, ValueError) as second_error:
                raise EvaluationError(
                    "Model did not return a valid Evaluation after one retry. "
                    f"First error: {first_error}. Second error: {second_error}."
                ) from second_error

    # -- message building -------------------------------------------------- #
    def _build_content(
        self,
        parsed_cv: ParsedCV,
        job_description: str,
        rubric: Rubric,
        *,
        pdf_bytes: Optional[bytes] = None,
    ) -> tuple[str, list[dict[str, Any]]]:
        system_prompt = build_system_prompt(job_description, rubric)
        include_images = rubric.requires_visual_review

        # pdf_direct (Phase 16): attach the CV as a native Anthropic document
        # block — Claude reads the PDF (layout included) itself, so no rendering
        # is needed and visual assessment works for creative roles too. The
        # rubric's requires_visual_review still only controls what the prompt
        # ASKS for (via include_images), which shapes build_user_text.
        if pdf_bytes is not None:
            document_block = {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": base64.b64encode(pdf_bytes).decode("ascii"),
                },
            }
            text_block = {"type": "text", "text": build_user_text(parsed_cv.raw_text, include_images)}
            # Document before the text, per Anthropic's PDF guidance.
            return system_prompt, [document_block, text_block]

        # render mode (default): text + rendered page images (images only when
        # the rubric asks for visual review — the cost/latency saving).
        user_content: list[dict[str, Any]] = [
            {"type": "text", "text": build_user_text(parsed_cv.raw_text, include_images)}
        ]
        if include_images:
            for page_image in parsed_cv.page_images[: settings.max_eval_pages]:
                try:
                    user_content.append(encode_image_anthropic_block(page_image.image_path))
                except (FileNotFoundError, OSError):
                    continue
        return system_prompt, user_content

    # -- SDK call ---------------------------------------------------------- #
    def _call_model(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        *,
        api_key: str,
        model: str,
    ) -> str:
        anthropic = _import_anthropic()
        client = self._get_client(api_key)

        attempts = max(1, settings.eval_max_network_attempts)
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                # Do not send `temperature`: Claude 4.5+ / Sonnet 5 reject it
                # as deprecated (400 invalid_request_error).
                response = client.messages.create(
                    model=model,
                    max_tokens=settings.eval_max_tokens,
                    system=system_prompt,
                    messages=messages,
                )
                return _extract_text(response)
            except (anthropic.APITimeoutError, anthropic.APIConnectionError) as exc:
                last_exc = exc
                self._maybe_backoff(attempt, attempts)
            except anthropic.APIStatusError as exc:
                status = getattr(exc, "status_code", None)
                if status in _RETRYABLE_STATUS:
                    last_exc = exc
                    self._maybe_backoff(attempt, attempts)
                    continue
                # Non-retryable client error (bad key, bad request, etc.).
                raise EvaluationError(
                    f"Anthropic request failed with {status}: {exc}"
                ) from exc

        raise EvaluationError(
            f"Anthropic request failed after {attempts} attempt(s): {last_exc}"
        ) from last_exc

    @staticmethod
    def _maybe_backoff(attempt: int, attempts: int) -> None:
        if attempt < attempts:
            time.sleep(settings.eval_network_backoff_s * attempt)

    # -- parsing ----------------------------------------------------------- #
    def _parse(
        self,
        content: str,
        parsed_cv: ParsedCV,
        rubric: Rubric,
        model: str,
    ) -> Evaluation:
        return build_evaluation(
            content,
            candidate_id=parsed_cv.candidate_id,
            rubric=rubric,
            evaluated_by=f"{self.name}:{model}",
        )


def _import_anthropic():
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - exercised only without the lib
        raise EvaluatorConfigError(
            "The 'anthropic' package is not installed. Install it with "
            "`pip install anthropic`."
        ) from exc
    return anthropic


def _extract_text(response: Any) -> str:
    """Concatenate the text content blocks of an Anthropic Message."""
    try:
        parts = [
            block.text
            for block in response.content
            if getattr(block, "type", None) == "text"
        ]
    except (AttributeError, TypeError) as exc:
        raise EvaluationError(
            f"Unexpected Anthropic response shape: {response!r}"[:300]
        ) from exc
    if not parts:
        raise EvaluationError("Anthropic response contained no text content.")
    return "".join(parts)
