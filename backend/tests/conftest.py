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
