"""Voice → text via Groq's Whisper transcription API (OpenAI-compatible).

The Groq key stays server-side: the browser records audio and posts the blob to
``POST /transcribe``; this module forwards it to Groq and returns the text.
"""
from __future__ import annotations

import httpx

from app.config import get_groq_api_key, get_groq_transcribe_model

GROQ_TRANSCRIBE_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
MAX_AUDIO_BYTES = 25 * 1024 * 1024  # Groq's upload limit for this endpoint


class TranscribeConfigError(RuntimeError):
    """Voice transcription isn't configured (no GROQ_API_KEY)."""


class TranscribeError(RuntimeError):
    """The transcription request failed (network / provider error)."""


def transcribe_audio(
    data: bytes,
    filename: str = "audio.webm",
    *,
    content_type: str = "audio/webm",
) -> str:
    """Return the transcript of ``data`` (recorded audio bytes), or raise."""
    if not data:
        raise TranscribeError("No audio was received.")
    if len(data) > MAX_AUDIO_BYTES:
        raise TranscribeError("Recording is too large to transcribe (max ~25 MB).")

    key = get_groq_api_key()
    if not key:
        raise TranscribeConfigError(
            "GROQ_API_KEY is not set — voice transcription is unavailable."
        )

    try:
        resp = httpx.post(
            GROQ_TRANSCRIBE_URL,
            headers={"Authorization": f"Bearer {key}"},
            data={"model": get_groq_transcribe_model(), "response_format": "json"},
            files={"file": (filename or "audio.webm", data, content_type or "audio/webm")},
            timeout=90.0,
        )
    except httpx.HTTPError as exc:
        raise TranscribeError(f"Could not reach the transcription service: {exc}") from exc

    if resp.status_code != 200:
        raise TranscribeError(
            f"Transcription failed ({resp.status_code}): {resp.text[:200]}"
        )
    try:
        return (resp.json().get("text") or "").strip()
    except ValueError as exc:  # non-JSON body
        raise TranscribeError("Transcription returned an unexpected response.") from exc
