"""Offline email sender — writes messages to a local outbox, sends nothing."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.email.base import EmailMessage, EmailSendResult


class MockEmailSender:
    """Default, fully-offline sender. Persists each message to ``data/outbox/``."""

    name = "mock"

    def send(self, message: EmailMessage) -> EmailSendResult:
        outbox = settings.data_dir / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc)
        candidate_id = message.metadata.get("candidate_id", "unknown")
        stamp = now.strftime("%Y%m%dT%H%M%S%fZ")
        path: Path = outbox / f"{candidate_id}_{stamp}.json"

        message_id = f"mock-{uuid.uuid4().hex[:12]}"
        payload = {
            "provider_message_id": message_id,
            "sent_at": now.isoformat(),
            "to": message.to,
            "to_name": message.to_name,
            "subject": message.subject,
            "html_body": message.html_body,
            "attachments": [a.filename for a in message.attachments],
            "metadata": message.metadata,
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        return EmailSendResult(success=True, provider_message_id=message_id)
