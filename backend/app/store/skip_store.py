"""Persisted 'skip list' of form submissions that can't be scored (non-PDF /
corrupt / unreadable image uploads). A re-pull skips these instead of
re-attempting them every time — which is what kept retrying the bad rows and
OOM-ing the instance.

Postgres-backed; a no-op on other backends (local/tests), where re-pulls are
cheap anyway. Keyed by (job_id, Drive file id).
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.config import get_store_backend


def _enabled() -> bool:
    return get_store_backend() == "postgres"


def record_skip(job_id: str, drive_file_id: str, *, name: str | None = None, reason: str | None = None) -> None:
    if not (drive_file_id and _enabled()):
        return
    try:
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from app.db.engine import session_scope
        from app.db.models import IngestSkipRow

        with session_scope() as s:
            stmt = pg_insert(IngestSkipRow).values(
                job_id=job_id,
                drive_file_id=drive_file_id,
                name=name,
                reason=(reason or "")[:500],
                created_at=datetime.now(timezone.utc),
            )
            # Idempotent: if it's already on the list, leave it.
            stmt = stmt.on_conflict_do_nothing(index_elements=["job_id", "drive_file_id"])
            s.execute(stmt)
    except Exception:  # noqa: BLE001 - skip-listing is best-effort, never fatal
        pass


def skipped_drive_ids(job_id: str) -> set[str]:
    if not _enabled():
        return set()
    try:
        from sqlalchemy import select

        from app.db.engine import session_scope
        from app.db.models import IngestSkipRow

        with session_scope() as s:
            rows = s.execute(
                select(IngestSkipRow.drive_file_id).where(IngestSkipRow.job_id == job_id)
            ).all()
        return {r[0] for r in rows}
    except Exception:  # noqa: BLE001
        return set()


def skipped_count(job_id: str) -> int:
    return len(skipped_drive_ids(job_id))


def clear_skips(job_id: str) -> None:
    if not _enabled():
        return
    try:
        from app.db.engine import session_scope
        from app.db.models import IngestSkipRow

        with session_scope() as s:
            s.query(IngestSkipRow).filter(IngestSkipRow.job_id == job_id).delete()
    except Exception:  # noqa: BLE001
        pass
