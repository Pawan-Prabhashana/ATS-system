"""Email sender contract + message/result models."""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class EmailAttachment(BaseModel):
    filename: str
    path: str = Field(..., description="Filesystem path to the file to attach.")


class EmailMessage(BaseModel):
    to: str = Field(..., description="Recipient email address.")
    to_name: Optional[str] = None
    subject: str
    html_body: str
    attachments: list[EmailAttachment] = Field(default_factory=list)
    # Free-form correlation metadata (e.g. {"candidate_id": ...}). Used by the
    # mock sender for outbox filenames and mappable to provider tags.
    metadata: dict[str, str] = Field(default_factory=dict)


class EmailSendResult(BaseModel):
    success: bool
    provider_message_id: Optional[str] = None
    error: Optional[str] = None


@runtime_checkable
class EmailSender(Protocol):
    """Sends an :class:`EmailMessage`, returning a typed result.

    Implementations should wrap runtime send failures into
    ``EmailSendResult(success=False, error=...)`` rather than raising, so one bad
    send never crashes the caller. Missing configuration (unset credentials) may
    raise :class:`~app.email.errors.EmailConfigError` at call time.
    """

    name: str

    def send(self, message: EmailMessage) -> EmailSendResult:
        ...
