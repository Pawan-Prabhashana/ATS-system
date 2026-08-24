"""Shared-gate authentication (Phase 12).

ONE set of credentials for the whole team — not per-user accounts. The goal is
to keep the public internet out, not to differentiate permissions. The API is
the real boundary: every route except ``GET /health`` requires a valid signed
token (the UI login is a convenience layered on top).

Transport: a Bearer JWT in the ``Authorization`` header. Cookie transport was
rejected for this setup — the Next.js frontend and FastAPI backend are
cross-origin (different localhost ports, which have moved across phases), where
httpOnly cross-origin ``Set-Cookie`` is fragile and causes the classic
"logs in then immediately logged out" bug. ``/auth/login`` returns the token in
the body; the frontend stores it and sends it back as ``Authorization: Bearer``.

Credentials + signing secret come from env (never hardcoded). Passwords are
compared in constant time against ``APP_AUTH_PASSWORD``; tokens are HS256-signed
with ``AUTH_SECRET_KEY``. ``AUTH_ENABLED=false`` turns the gate into a no-op for
LOCAL DEV only.
"""
from __future__ import annotations

import hmac
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from app.config import (
    get_app_auth_password,
    get_app_auth_username,
    get_auth_enabled,
    get_auth_secret_key,
    get_auth_token_ttl_hours,
)

JWT_ALGORITHM = "HS256"
_TOKEN_TYPE = "access"


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_at: datetime
    username: str


class MeResponse(BaseModel):
    authenticated: bool
    username: Optional[str] = None
    auth_enabled: bool = True


class AuthConfigError(RuntimeError):
    """Server-side auth misconfiguration (missing secret or password)."""


# --------------------------------------------------------------------------- #
# Token + credential helpers
# --------------------------------------------------------------------------- #
def _require_secret() -> str:
    secret = get_auth_secret_key()
    if not secret:
        raise AuthConfigError("AUTH_SECRET_KEY is not set — cannot sign or verify sessions.")
    return secret


def create_access_token(username: str) -> tuple[str, datetime]:
    secret = _require_secret()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=get_auth_token_ttl_hours())
    payload = {
        "sub": username,
        "type": _TOKEN_TYPE,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM), expires


def decode_token(token: str) -> dict:
    """Decode + verify a token. Raises jwt.* on invalid/expired, AuthConfigError
    if the server has no secret configured."""
    return jwt.decode(token, _require_secret(), algorithms=[JWT_ALGORITHM])


def verify_credentials(username: str, password: str) -> bool:
    expected_user = get_app_auth_username()
    expected_pass = get_app_auth_password()
    if not expected_pass:
        raise AuthConfigError("APP_AUTH_PASSWORD is not set — cannot authenticate.")
    # Constant-time compare on both fields (avoid short-circuit timing leaks).
    user_ok = hmac.compare_digest(username or "", expected_user or "")
    pass_ok = hmac.compare_digest(password or "", expected_pass or "")
    return user_ok and pass_ok


def _bearer_token(request: Request) -> Optional[str]:
    header = request.headers.get("Authorization") or ""
    if header[:7].lower() == "bearer ":
        return header[7:].strip() or None
    return None


# --------------------------------------------------------------------------- #
# Dependency — protects every route it's attached to
# --------------------------------------------------------------------------- #
def require_auth(request: Request) -> dict:
    """Allow the request only with a valid session.

    No-op when ``AUTH_ENABLED=false`` (local dev). Otherwise a missing, invalid,
    or expired token is a clean 401 — never a 500 for the unauthenticated case.
    A missing server secret is the one 500 (a deployment error, not a client one).
    """
    if not get_auth_enabled():
        return {"sub": get_app_auth_username(), "auth_disabled": True}

    token = _bearer_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return decode_token(token)
    except AuthConfigError:
        raise HTTPException(status_code=500, detail="Authentication is misconfigured on the server.")
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401, detail="Session expired.", headers={"WWW-Authenticate": "Bearer"}
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=401, detail="Invalid session.", headers={"WWW-Authenticate": "Bearer"}
        )


# --------------------------------------------------------------------------- #
# Routes — mounted WITHOUT the auth dependency (login must be reachable)
# --------------------------------------------------------------------------- #
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest) -> LoginResponse:
    try:
        ok = verify_credentials(body.username, body.password)
    except AuthConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    if not ok:
        raise HTTPException(status_code=401, detail="Incorrect username or password.")
    try:
        token, expires = create_access_token(body.username)
    except AuthConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return LoginResponse(token=token, expires_at=expires, username=body.username)


@router.post("/logout")
def logout() -> dict:
    # Stateless JWT — nothing to revoke server-side; the client discards its token.
    return {"ok": True}


@router.get("/me", response_model=MeResponse)
def me(request: Request) -> MeResponse:
    """Report whether the current session is valid. Never 401s — it's a probe."""
    if not get_auth_enabled():
        return MeResponse(authenticated=True, username=get_app_auth_username(), auth_enabled=False)
    token = _bearer_token(request)
    if not token:
        return MeResponse(authenticated=False, auth_enabled=True)
    try:
        payload = decode_token(token)
    except Exception:
        return MeResponse(authenticated=False, auth_enabled=True)
    return MeResponse(authenticated=True, username=payload.get("sub"), auth_enabled=True)
