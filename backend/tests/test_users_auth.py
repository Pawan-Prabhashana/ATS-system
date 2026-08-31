"""Multi-user auth: password hashing + the authenticate() env-admin fallback."""
import pytest

from app.auth import authenticate, create_access_token, decode_token
from app.users import hash_password, verify_password


def test_password_hash_roundtrip():
    h = hash_password("Catalist!2026")
    assert h.startswith("pbkdf2_sha256$")
    assert verify_password("Catalist!2026", h)
    assert not verify_password("wrong", h)
    # Two hashes of the same password differ (random salt) but both verify.
    assert h != hash_password("Catalist!2026")


def test_verify_password_rejects_garbage():
    assert not verify_password("x", "not-a-valid-hash")
    assert not verify_password("x", "")


def test_authenticate_env_admin_fallback(monkeypatch):
    # No users table on the default (json) backend -> env admin is used.
    monkeypatch.setenv("APP_AUTH_USERNAME", "admin")
    monkeypatch.setenv("APP_AUTH_PASSWORD", "secret-pw")
    principal = authenticate("admin", "secret-pw")
    assert principal == {"username": "admin", "full_name": "admin"}
    assert authenticate("admin", "wrong") is None
    assert authenticate("nobody", "secret-pw") is None


def test_token_carries_full_name(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET_KEY", "unit-test-secret-key-at-least-32-bytes-long")
    token, _ = create_access_token("apassela", "Abdul Ashraff")
    payload = decode_token(token)
    assert payload["sub"] == "apassela"
    assert payload["name"] == "Abdul Ashraff"
