"""Phase 13: deploy-facing config — GOOGLE_SERVICE_ACCOUNT_JSON + FRONTEND_ORIGIN."""
from __future__ import annotations

from pathlib import Path


def test_service_account_json_materialized_to_file(monkeypatch):
    import app.config as cfg

    monkeypatch.setattr(cfg, "_MATERIALIZED_SA_JSON", None)
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)
    payload = '{"type":"service_account","project_id":"demo","client_email":"x@y.iam"}'
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", payload)

    path = cfg.get_google_service_account_file()
    assert path is not None
    p = Path(path)
    assert p.exists()
    assert p.read_text(encoding="utf-8") == payload


def test_service_account_file_path_takes_precedence(monkeypatch, tmp_path):
    import app.config as cfg

    monkeypatch.setattr(cfg, "_MATERIALIZED_SA_JSON", None)
    key = tmp_path / "sa.json"
    key.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", str(key))
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", '{"ignored":true}')

    # Explicit file path wins over the JSON string.
    assert cfg.get_google_service_account_file() == str(key)


def test_frontend_origin_appended_to_cors(monkeypatch):
    monkeypatch.delenv("CATALIST_CORS_ORIGINS", raising=False)
    monkeypatch.setenv("FRONTEND_ORIGIN", "https://catalist.vercel.app/")  # trailing slash

    from app.main import _cors_origins

    origins = _cors_origins()
    assert "https://catalist.vercel.app" in origins  # slash trimmed, exact origin
    assert "http://localhost:3000" in origins  # localhost defaults kept for dev


def test_no_frontend_origin_keeps_defaults(monkeypatch):
    monkeypatch.delenv("CATALIST_CORS_ORIGINS", raising=False)
    monkeypatch.delenv("FRONTEND_ORIGIN", raising=False)

    from app.main import _cors_origins

    origins = _cors_origins()
    assert "http://localhost:3000" in origins
    assert all(not o.startswith("https://") for o in origins)  # nothing hosted leaks in
