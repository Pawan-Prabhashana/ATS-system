"""Persistence for team-chat messages — JSON (local/tests) and SQL (Postgres).

Same seam as the other stores: callers depend on the ``ChatRepository`` Protocol
via ``get_chat_store()``. Messages are append-only; a monotonic integer ``id`` is
the cursor the frontend polls with (``list_since``).
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, runtime_checkable

from app.config import DATA_DIR, get_store_backend
from app.models import ChatMessage


@runtime_checkable
class ChatRepository(Protocol):
    def add(self, username: str, full_name: str, body: str) -> ChatMessage: ...
    def list_since(self, after_id: int = 0, limit: int = 500) -> list[ChatMessage]: ...
    def recent(self, limit: int = 200) -> list[ChatMessage]: ...


def _chat_store_path() -> Path:
    override = os.getenv("CATALIST_CHAT_STORE_PATH")
    return Path(override) if override else DATA_DIR / "chat.json"


class JSONChatStore:
    """File-backed chat store (a JSON list + a sequence counter)."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else _chat_store_path()
        self._lock = threading.Lock()

    def _load(self) -> dict:
        if not self.path.exists():
            return {"seq": 0, "messages": []}
        with self.path.open(encoding="utf-8") as fh:
            return json.load(fh)

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".chat-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def add(self, username: str, full_name: str, body: str) -> ChatMessage:
        with self._lock:
            data = self._load()
            seq = int(data.get("seq", 0)) + 1
            msg = ChatMessage(
                id=seq,
                username=username,
                full_name=full_name,
                body=body,
                created_at=datetime.now(timezone.utc),
            )
            data["seq"] = seq
            data.setdefault("messages", []).append(msg.model_dump(mode="json"))
            self._write(data)
            return msg

    def list_since(self, after_id: int = 0, limit: int = 500) -> list[ChatMessage]:
        msgs = [ChatMessage.model_validate(m) for m in self._load().get("messages", [])]
        newer = [m for m in msgs if m.id > after_id]
        return sorted(newer, key=lambda m: m.id)[:limit]

    def recent(self, limit: int = 200) -> list[ChatMessage]:
        msgs = sorted(
            (ChatMessage.model_validate(m) for m in self._load().get("messages", [])),
            key=lambda m: m.id,
        )
        return msgs[-limit:]


class SQLChatStore:
    def _scope(self):
        from app.db.engine import session_scope

        return session_scope()

    @staticmethod
    def _to_msg(row) -> ChatMessage:
        created = row.created_at
        if created is not None and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return ChatMessage(
            id=row.id,
            username=row.username,
            full_name=row.full_name,
            body=row.body,
            created_at=created,
        )

    def add(self, username: str, full_name: str, body: str) -> ChatMessage:
        from app.db.models import ChatMessageRow

        with self._scope() as s:
            row = ChatMessageRow(
                username=username,
                full_name=full_name,
                body=body,
                created_at=datetime.now(timezone.utc),
            )
            s.add(row)
            s.flush()  # assign the autoincrement id
            return self._to_msg(row)

    def list_since(self, after_id: int = 0, limit: int = 500) -> list[ChatMessage]:
        from sqlalchemy import select

        from app.db.models import ChatMessageRow

        with self._scope() as s:
            rows = (
                s.execute(
                    select(ChatMessageRow)
                    .where(ChatMessageRow.id > after_id)
                    .order_by(ChatMessageRow.id.asc())
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            return [self._to_msg(r) for r in rows]

    def recent(self, limit: int = 200) -> list[ChatMessage]:
        from sqlalchemy import select

        from app.db.models import ChatMessageRow

        with self._scope() as s:
            rows = (
                s.execute(
                    select(ChatMessageRow).order_by(ChatMessageRow.id.desc()).limit(limit)
                )
                .scalars()
                .all()
            )
            return [self._to_msg(r) for r in reversed(rows)]


def get_chat_store() -> ChatRepository:
    if get_store_backend() == "postgres":
        return SQLChatStore()
    return JSONChatStore()
