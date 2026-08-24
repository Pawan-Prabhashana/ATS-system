"""Phase 12: shared-gate auth enforced on the API (offline).

Marked ``real_auth`` so the conftest bypass is OFF — these exercise the genuine
dependency: protected routes 401 without a session, 200 with a valid token,
/health stays public, login success/failure, expired/invalid tokens 401, and
the AUTH_ENABLED=false bypass.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from app.auth import JWT_ALGORITHM
from app.main import app

pytestmark = pytest.mark.real_auth

client = TestClient(app)

SECRET = "unit-test-secret-key-at-least-32-bytes-long"


@pytest.fixture(autouse=True)
def _creds(monkeypatch):
    monkeypatch.setenv("APP_AUTH_USERNAME", "admin")
    monkeypatch.setenv("APP_AUTH_PASSWORD", "s3cret-pw")
    monkeypatch.setenv("AUTH_SECRET_KEY", SECRET)
    monkeypatch.setenv("AUTH_ENABLED", "true")


def _login(username="admin", password="s3cret-pw"):
    return client.post("/auth/login", json={"username": username, "password": password})


# --------------------------------------------------------------------------- #
# Public vs protected
# --------------------------------------------------------------------------- #
def test_health_is_public():
    assert client.get("/health").status_code == 200


def test_protected_route_without_session_is_401():
    r = client.get("/jobs")
    assert r.status_code == 401
    assert "detail" in r.json()  # clean typed body, not a 500 stack trace


def test_protected_route_with_valid_token_is_200():
    token = _login().json()["token"]
    r = client.get("/jobs", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


# --------------------------------------------------------------------------- #
# Login
# --------------------------------------------------------------------------- #
def test_login_success_returns_token():
    r = _login()
    assert r.status_code == 200
    body = r.json()
    assert body["token"] and body["username"] == "admin"
    # Token is a valid HS256 JWT for this user.
    payload = jwt.decode(body["token"], SECRET, algorithms=[JWT_ALGORITHM])
    assert payload["sub"] == "admin"


def test_login_wrong_password_is_401():
    assert _login(password="nope").status_code == 401


def test_login_wrong_username_is_401():
    assert _login(username="root").status_code == 401


# --------------------------------------------------------------------------- #
# Token validation
# --------------------------------------------------------------------------- #
def test_expired_token_is_401():
    expired = jwt.encode(
        {
            "sub": "admin",
            "type": "access",
            "exp": int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp()),
        },
        SECRET,
        algorithm=JWT_ALGORITHM,
    )
    r = client.get("/jobs", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401
    assert "expired" in r.json()["detail"].lower()


def test_token_signed_with_wrong_secret_is_401():
    forged = jwt.encode({"sub": "admin", "exp": 9999999999}, "attacker-secret", algorithm=JWT_ALGORITHM)
    r = client.get("/jobs", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


def test_malformed_authorization_header_is_401():
    assert client.get("/jobs", headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401
    assert client.get("/jobs", headers={"Authorization": "Basic abc"}).status_code == 401


# --------------------------------------------------------------------------- #
# /auth/me + logout
# --------------------------------------------------------------------------- #
def test_me_reflects_session_state():
    assert client.get("/auth/me").json()["authenticated"] is False
    token = _login().json()["token"]
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["authenticated"] is True and me["username"] == "admin"


def test_logout_ok():
    assert client.post("/auth/logout").json()["ok"] is True


# --------------------------------------------------------------------------- #
# AUTH_ENABLED=false bypass (local dev only)
# --------------------------------------------------------------------------- #
def test_auth_disabled_bypasses(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    assert client.get("/jobs").status_code == 200
    me = client.get("/auth/me").json()
    assert me["authenticated"] is True and me["auth_enabled"] is False
