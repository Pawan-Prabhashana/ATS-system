"""In-process progress registry for long-running background jobs (pull, rescore).

A synchronous HTTP request that scores hundreds of CVs would exceed request
timeouts and give the user no feedback. Instead those runs happen in a background
thread that reports progress here; the frontend polls a status endpoint and shows
"X of Y". State is in-memory (per web instance) — fine because the instance that
runs the job is the one serving the poll. It resets if the instance restarts,
which is safe: pulls are idempotent (dedup) and can simply be re-run.

Note (Render Free): the single web instance sleeps after ~15 min idle, so a
background job only runs while the service is awake (it stays awake while
actively working and being polled). Continuous/scheduled work while idle needs a
paid worker or an external cron ping — see DEPLOY-NOTES.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional

_LOCK = threading.Lock()
_TASKS: dict[str, dict] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def try_start(key: str, kind: str, total: int = 0) -> bool:
    """Mark ``key`` as running if it isn't already. Returns False if a run for
    this key is already in progress (so callers don't start a duplicate)."""
    with _LOCK:
        t = _TASKS.get(key)
        if t and t.get("status") == "running":
            return False
        _TASKS[key] = {
            "kind": kind,
            "status": "running",
            "total": total,
            "processed": 0,
            "started_at": _now(),
            "finished_at": None,
            "error": None,
            "summary": None,
        }
        return True


def set_total(key: str, total: int) -> None:
    with _LOCK:
        if key in _TASKS:
            _TASKS[key]["total"] = total


def report(key: str, processed: int, total: Optional[int] = None) -> None:
    with _LOCK:
        t = _TASKS.get(key)
        if not t:
            return
        t["processed"] = processed
        if total is not None:
            t["total"] = total


def finish(key: str, *, summary: Optional[dict] = None, error: Optional[str] = None) -> None:
    with _LOCK:
        t = _TASKS.get(key)
        if not t:
            return
        t["status"] = "error" if error else "done"
        t["error"] = error
        t["summary"] = summary
        t["finished_at"] = _now()


def snapshot(key: str) -> Optional[dict]:
    with _LOCK:
        t = _TASKS.get(key)
        return dict(t) if t else None
