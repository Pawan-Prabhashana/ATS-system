"""Shared pytest fixtures."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.config import settings

SAMPLE_DIR = settings.sample_data_dir


@pytest.fixture(scope="session")
def text_cv_path() -> Path:
    path = SAMPLE_DIR / "sample_cv_text.pdf"
    if not path.exists():
        pytest.skip("Run scripts/generate_samples.py to create sample PDFs.")
    return path


@pytest.fixture(scope="session")
def scanned_cv_path() -> Path:
    path = SAMPLE_DIR / "sample_cv_scanned.pdf"
    if not path.exists():
        pytest.skip("Run scripts/generate_samples.py to create sample PDFs.")
    return path


@pytest.fixture
def output_root(tmp_path) -> Path:
    """Isolate parser output per test."""
    return tmp_path / "output"


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path, monkeypatch):
    """Point per-candidate artifact writes at a throwaway dir per test.

    Keeps the repo's backend/data clean and isolates ingestion artifacts.
    """
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path / "data")


@pytest.fixture(autouse=True)
def _default_cv_mode_render(monkeypatch):
    """Pin CV_MODE=render for the offline suite.

    Since Phase 17 the CV_MODE default is ``pdf_direct``, which requires
    ``EVALUATOR_MODE=anthropic``. The offline suite runs on the ``mock``
    evaluator (no network), so the render path is the ONLY valid path here — we
    pin it explicitly rather than let the new default trip the pdf_direct guard.
    Tests that specifically exercise pdf_direct override this in their own body
    (they set ``CV_MODE=pdf_direct``, which wins as it runs after this fixture).
    The new default itself is proven directly in ``test_pdf_direct.py``.
    """
    monkeypatch.setenv("CV_MODE", "render")


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real_auth: exercise the real auth dependency (no test bypass) — used by "
        "the auth test module; every other test runs authenticated via a bypass.",
    )


@pytest.fixture(autouse=True)
def _authenticated(request, monkeypatch):
    """Make every route test run as an authenticated session.

    Phase 12 gates the whole API behind ``require_auth``. Rather than thread a
    real token through every existing test, we set valid server-side creds and
    override the dependency with a valid principal — the standard FastAPI test
    pattern. Tests marked ``real_auth`` skip the override so they can exercise
    the genuine 401 / login / expiry behavior.
    """
    monkeypatch.setenv("APP_AUTH_USERNAME", "tester")
    monkeypatch.setenv("APP_AUTH_PASSWORD", "test-password")
    monkeypatch.setenv("AUTH_SECRET_KEY", "unit-test-secret-key-at-least-32-bytes-long")
    monkeypatch.setenv("AUTH_ENABLED", "true")

    from app.auth import require_auth
    from app.main import app

    if "real_auth" in request.keywords:
        app.dependency_overrides.pop(require_auth, None)
        yield
        return

    app.dependency_overrides[require_auth] = lambda: {"sub": "tester"}
    yield
    app.dependency_overrides.pop(require_auth, None)


@pytest.fixture(scope="session")
def rubric():
    """General (content-only) rubric — requires_visual_review is False."""
    from app.models import Rubric

    path = SAMPLE_DIR / "rubric.json"
    return Rubric.model_validate_json(path.read_text())


@pytest.fixture(scope="session")
def design_rubric():
    """Design rubric — requires_visual_review is True (page images sent)."""
    from app.models import Rubric

    path = SAMPLE_DIR / "rubric_design.json"
    return Rubric.model_validate_json(path.read_text())
