"""Individual reviewer accounts + password hashing.

Multi-user auth (so the system can attribute each shortlist/reject/assignment to
the person who did it). Accounts live in the ``users`` table on the Postgres
backend; passwords are stored ONLY as a pbkdf2-sha256 hash (stdlib — no extra
dependency), never as plaintext.

Non-Postgres backends (local JSON / offline tests) have no users table; the
accessors below no-op there and auth falls back to the single env admin account.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel

from app.config import get_store_backend

_PBKDF2_ALGO = "pbkdf2_sha256"
_PBKDF2_ITER = 200_000


class User(BaseModel):
    username: str
    full_name: str
    password_hash: str
    active: bool = True
    is_admin: bool = False


# --------------------------------------------------------------------------- #
# Password hashing (pbkdf2-sha256, constant-time verify)
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITER)
    return f"{_PBKDF2_ALGO}${_PBKDF2_ITER}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != _PBKDF2_ALGO:
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


# --------------------------------------------------------------------------- #
# Accessors — Postgres only; a no-op elsewhere (auth falls back to env admin)
# --------------------------------------------------------------------------- #
def _users_enabled() -> bool:
    return get_store_backend() == "postgres"


def get_user(username: str) -> Optional[User]:
    """Look up a user by username, or None (also None on non-Postgres backends,
    or if the DB/table isn't reachable — auth then uses the env admin)."""
    if not username or not _users_enabled():
        return None
    try:
        from app.db.engine import session_scope
        from app.db.models import UserRow

        with session_scope() as s:
            row = s.get(UserRow, username)
            if row is None:
                return None
            return User(
                username=row.username,
                full_name=row.full_name,
                password_hash=row.password_hash,
                active=row.active,
                is_admin=bool(row.is_admin),
            )
    except Exception:  # noqa: BLE001 - unreachable DB -> fall back to env admin
        return None


def list_users() -> list[User]:
    if not _users_enabled():
        return []
    try:
        from app.db.engine import session_scope
        from app.db.models import UserRow
        from sqlalchemy import select

        with session_scope() as s:
            rows = s.execute(select(UserRow)).scalars().all()
            return [
                User(
                    username=r.username,
                    full_name=r.full_name,
                    password_hash=r.password_hash,
                    active=r.active,
                    is_admin=bool(r.is_admin),
                )
                for r in rows
            ]
    except Exception:  # noqa: BLE001
        return []


def upsert_user(
    username: str,
    full_name: str,
    password: str,
    active: bool = True,
    is_admin: bool = False,
) -> User:
    """Create or replace a user with a freshly hashed password. Postgres only."""
    from app.db.engine import session_scope
    from app.db.models import UserRow

    pw_hash = hash_password(password)
    with session_scope() as s:
        row = s.get(UserRow, username)
        if row is None:
            row = UserRow(username=username, created_at=datetime.now(timezone.utc))
            s.add(row)
        row.full_name = full_name
        row.password_hash = pw_hash
        row.active = active
        row.is_admin = is_admin
    return User(
        username=username, full_name=full_name, password_hash=pw_hash, active=active, is_admin=is_admin
    )
