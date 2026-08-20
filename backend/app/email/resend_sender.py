"""Real email sender backed by the Resend API.

Uses a plain ``httpx`` POST rather than the ``resend`` SDK: we already depend on
httpx, Resend's send endpoint is a single JSON POST, and this keeps the
dependency surface (and the swap-a-provider story) minimal.

Credentials are read at call time only — importing/constructing this class never
requires ``RESEND_API_KEY`` / ``RESEND_FROM_EMAIL``. Missing config raises
``EmailConfigError`` when ``send`` runs; runtime failures (bad key accepted by
env but rejected by the API, invalid recipient, network) come back as
``EmailSendResult(success=False, ...)`` instead of raising.
"""
from __future__ import annotations

import base64
from pathlib import Path

import httpx

from app.config import (
    get_resend_api_key,
    get_resend_from_email,
    get_resend_reply_to,
    settings,
)
from app.email.base import EmailMessage, EmailSendResult
from app.email.errors import EmailConfigError

RESEND_ENDPOINT = "https://api.resend.com/emails"


class ResendEmailSender:
    """Sends via Resend (https://resend.com)."""

    name = "resend"

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        # Injectable for tests; no credentials touched at construction time.
        self._injected_client = client

    def send(self, message: EmailMessage) -> EmailSendResult:
        api_key = get_resend_api_key()
        from_email = get_resend_from_email()
        if not api_key or not from_email:
            raise EmailConfigError(
                "RESEND_API_KEY and RESEND_FROM_EMAIL must both be set to use the "
                "Resend email sender (EMAIL_MODE=resend)."
            )

        try:
            payload = self._build_payload(message, from_email)
        except OSError as exc:
            return EmailSendResult(
                success=False, error=f"Could not read attachment: {exc}"
            )

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            client = self._injected_client or httpx.Client(
                timeout=settings.eval_request_timeout_s
            )
            try:
                response = client.post(RESEND_ENDPOINT, json=payload, headers=headers)
            finally:
                if self._injected_client is None:
                    client.close()
        except httpx.HTTPError as exc:
            return EmailSendResult(success=False, error=f"Network error: {exc}")

        if response.status_code >= 400:
            return EmailSendResult(
                success=False,
                error=f"Resend API {response.status_code}: {response.text[:300]}",
            )

        try:
            message_id = response.json().get("id")
        except ValueError:
            message_id = None
        return EmailSendResult(success=True, provider_message_id=message_id)

    def _build_payload(self, message: EmailMessage, from_email: str) -> dict:
        attachments = []
        for att in message.attachments:
            content = Path(att.path).read_bytes()
            attachments.append(
                {
                    "filename": att.filename,
                    "content": base64.b64encode(content).decode("ascii"),
                }
            )
        to = f"{message.to_name} <{message.to}>" if message.to_name else message.to
        payload: dict = {
            "from": from_email,
            "to": [to],
            "subject": message.subject,
            "html": message.html_body,
        }
        # Optional Reply-To so replies land in a real inbox, not the from-address.
        reply_to = get_resend_reply_to()
        if reply_to:
            payload["reply_to"] = reply_to
        if attachments:
            payload["attachments"] = attachments
        if message.metadata:
            # Resend supports string tags for correlation.
            payload["tags"] = [
                {"name": k, "value": v} for k, v in message.metadata.items()
            ]
        return payload
