"""Central configuration for the parsing pipeline.

Kept intentionally simple (module-level constants + a settings object) so there
are no hidden dependencies. Values can be overridden via environment variables.
"""
from __future__ import annotations

import os
from pathlib import Path

# Repository/backend root (…/backend)
BACKEND_ROOT = Path(__file__).resolve().parent.parent

# Where per-candidate rendered page images are written.
OUTPUT_DIR = Path(os.getenv("CATALIST_OUTPUT_DIR", BACKEND_ROOT / "output"))

# Bundled sample data.
SAMPLE_DATA_DIR = BACKEND_ROOT / "sample_data"

# Below this many characters of extracted text the CV is flagged "low"
# (likely scanned / image-only), signalling later phases to lean on the images.
LOW_TEXT_CHAR_THRESHOLD = int(os.getenv("CATALIST_LOW_TEXT_THRESHOLD", "100"))

# DPI used when rasterising PDF pages to PNG.
RENDER_DPI = int(os.getenv("CATALIST_RENDER_DPI", "150"))


# --------------------------------------------------------------------------- #
# Evaluation (Phase 2)
# --------------------------------------------------------------------------- #
# Which evaluator the factory hands out: "mock" (offline, default) or "real"
# (OpenRouter vision+text). Read at call time via get_evaluator_mode() so tests
# and deployments can flip it without re-importing.
DEFAULT_EVALUATOR_MODE = "mock"

# OpenRouter (OpenAI-compatible) endpoint + default model. The model is chosen
# by env var only — nothing else in the codebase assumes a specific provider,
# so switching to e.g. "openai/gpt-4o" is a pure env change.
OPENROUTER_API_BASE = os.getenv(
    "OPENROUTER_API_BASE", "https://openrouter.ai/api/v1"
)
DEFAULT_OPENROUTER_MODEL = "anthropic/claude-3.5-sonnet"

# Native Anthropic API (EVALUATOR_MODE=anthropic).
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"

# Max output tokens requested from the model (Anthropic requires this; harmless
# elsewhere). Generous enough for a full multi-criterion Evaluation JSON.
EVAL_MAX_TOKENS = int(os.getenv("CATALIST_EVAL_MAX_TOKENS", "1500"))

# Cap how many rendered page images we send to the vision model, to control
# token cost. The first pages carry the most signal (header, summary, recent
# experience, overall layout).
MAX_EVAL_PAGES = int(os.getenv("CATALIST_MAX_EVAL_PAGES", "3"))

# Image downscale/compression target before base64-encoding for the API.
IMAGE_MAX_LONG_EDGE_PX = int(os.getenv("CATALIST_IMAGE_MAX_LONG_EDGE", "1200"))
IMAGE_JPEG_QUALITY = int(os.getenv("CATALIST_IMAGE_JPEG_QUALITY", "80"))

# Network behaviour for the evaluation request (separate from JSON-retry logic).
EVAL_REQUEST_TIMEOUT_S = float(os.getenv("CATALIST_EVAL_TIMEOUT", "60"))
EVAL_MAX_NETWORK_ATTEMPTS = int(os.getenv("CATALIST_EVAL_MAX_ATTEMPTS", "2"))
EVAL_NETWORK_BACKOFF_S = float(os.getenv("CATALIST_EVAL_BACKOFF", "1.0"))


# --------------------------------------------------------------------------- #
# Intake + candidate store (Phase 3)
# --------------------------------------------------------------------------- #
# Which intake source the factory hands out: "local" (offline CSV fixtures,
# default) or "google" (Google Sheets/Drive).
DEFAULT_INTAKE_MODE = "local"

# Local working data (candidate store, ingest scratch).
DATA_DIR = Path(os.getenv("CATALIST_DATA_DIR", BACKEND_ROOT / "data"))
DEFAULT_CANDIDATE_STORE_PATH = DATA_DIR / "candidates.json"
DEFAULT_JOB_STORE_PATH = DATA_DIR / "jobs.json"

# Which persistence backend the store factory hands out: "json" (local JSON
# files, default — keeps the offline suite byte-for-byte) or "postgres" (any
# Postgres via DATABASE_URL, e.g. Supabase). Read at call time so deployments
# flip it via env without a code change; the SQL layer is only imported when
# selected.
DEFAULT_STORE_BACKEND = "json"


# --------------------------------------------------------------------------- #
# Email / assignment dispatch (Phase 5)
# --------------------------------------------------------------------------- #
# Which email sender the factory hands out: "mock" (offline, writes to an
# outbox dir, default) or "resend" (real, via the Resend API).
DEFAULT_EMAIL_MODE = "mock"


# -- Call-time getters for env-dependent values ----------------------------- #
# These read os.environ on each call so that (a) a missing API key errors on
# first use rather than at import, and (b) tests can monkeypatch freely.
def get_evaluator_mode() -> str:
    return os.getenv("EVALUATOR_MODE", DEFAULT_EVALUATOR_MODE).strip().lower()


def get_openrouter_model() -> str:
    return os.getenv("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL)


def get_openrouter_api_key() -> str | None:
    return os.getenv("OPENROUTER_API_KEY")


def get_anthropic_model() -> str:
    return os.getenv("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL)


def get_anthropic_api_key() -> str | None:
    return os.getenv("ANTHROPIC_API_KEY")


def get_intake_mode() -> str:
    return os.getenv("INTAKE_MODE", DEFAULT_INTAKE_MODE).strip().lower()


def get_candidate_store_path() -> Path:
    override = os.getenv("CATALIST_CANDIDATE_STORE_PATH")
    return Path(override) if override else DEFAULT_CANDIDATE_STORE_PATH


def get_job_store_path() -> Path:
    override = os.getenv("CATALIST_JOB_STORE_PATH")
    return Path(override) if override else DEFAULT_JOB_STORE_PATH


def get_store_backend() -> str:
    return os.getenv("STORE_BACKEND", DEFAULT_STORE_BACKEND).strip().lower()


def get_database_url() -> str | None:
    """Return the SQLAlchemy connection URL, or None if unset.

    Read at call time (never at import) — the same lazy pattern as every other
    credential. When ``STORE_BACKEND=postgres`` but this is missing, the DB layer
    raises a clear config error on first use rather than crashing at import.
    """
    raw = (os.getenv("DATABASE_URL") or "").strip()
    return raw or None


# --------------------------------------------------------------------------- #
# Authentication (Phase 12) — shared-gate login (one credential set for the team)
# --------------------------------------------------------------------------- #
def get_auth_enabled() -> bool:
    """Whether the API enforces auth. Default TRUE. Only an explicit falsey value
    disables it — a LOCAL DEV convenience; production/hosted must leave it on."""
    raw = os.getenv("AUTH_ENABLED")
    if raw is None:
        return True
    return raw.strip().lower() not in ("false", "0", "no", "off")


def get_app_auth_username() -> str:
    return os.getenv("APP_AUTH_USERNAME", "admin")


def get_app_auth_password() -> str | None:
    return os.getenv("APP_AUTH_PASSWORD")


def get_auth_secret_key() -> str | None:
    return os.getenv("AUTH_SECRET_KEY")


def get_auth_token_ttl_hours() -> int:
    try:
        return int(os.getenv("AUTH_TOKEN_TTL_HOURS", "12"))
    except ValueError:
        return 12


def get_google_sheet_id() -> str | None:
    return os.getenv("GOOGLE_SHEET_ID")


def get_google_service_account_file() -> str | None:
    """Return the service-account JSON path, or None if none is configured.

    Relative paths resolve against the backend root. If the env var is unset
    (or empty), fall back to ``backend/service-account.json`` when that file
    exists so local ``.env`` / uvicorn ``--env-file`` quirks cannot hide it.
    """
    raw = (os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE") or "").strip().strip('"').strip("'")
    if raw:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = BACKEND_ROOT / path
        return str(path)
    default = BACKEND_ROOT / "service-account.json"
    return str(default) if default.exists() else None


def get_email_mode() -> str:
    return os.getenv("EMAIL_MODE", DEFAULT_EMAIL_MODE).strip().lower()


def get_resend_api_key() -> str | None:
    return os.getenv("RESEND_API_KEY")


def get_resend_from_email() -> str | None:
    return os.getenv("RESEND_FROM_EMAIL")


def get_resend_reply_to() -> str | None:
    """Optional Reply-To address for real sends. When set, candidates replying
    to an assignment email reach this inbox instead of the send-only from-address.
    Read at call time; unset (or blank) means no reply_to is sent."""
    raw = (os.getenv("RESEND_REPLY_TO") or "").strip()
    return raw or None


def get_assignment_deadline_days() -> int:
    try:
        return int(os.getenv("ASSIGNMENT_DEADLINE_DAYS", "5"))
    except ValueError:
        return 5


class Settings:
    """Lightweight settings holder (avoids a hard pydantic-settings dependency)."""

    output_dir: Path = OUTPUT_DIR
    sample_data_dir: Path = SAMPLE_DATA_DIR
    data_dir: Path = DATA_DIR
    low_text_char_threshold: int = LOW_TEXT_CHAR_THRESHOLD
    render_dpi: int = RENDER_DPI

    # Evaluation
    openrouter_api_base: str = OPENROUTER_API_BASE
    default_openrouter_model: str = DEFAULT_OPENROUTER_MODEL
    default_anthropic_model: str = DEFAULT_ANTHROPIC_MODEL
    eval_max_tokens: int = EVAL_MAX_TOKENS
    max_eval_pages: int = MAX_EVAL_PAGES
    image_max_long_edge_px: int = IMAGE_MAX_LONG_EDGE_PX
    image_jpeg_quality: int = IMAGE_JPEG_QUALITY
    eval_request_timeout_s: float = EVAL_REQUEST_TIMEOUT_S
    eval_max_network_attempts: int = EVAL_MAX_NETWORK_ATTEMPTS
    eval_network_backoff_s: float = EVAL_NETWORK_BACKOFF_S


settings = Settings()
