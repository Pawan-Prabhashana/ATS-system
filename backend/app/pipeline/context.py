"""Loading the default job description + rubric from sample_data."""
from __future__ import annotations

from pathlib import Path

from app.config import settings
from app.models import Rubric

DEFAULT_RUBRIC_PATH = settings.sample_data_dir / "rubric.json"
DEFAULT_JD_PATH = settings.sample_data_dir / "job_description.txt"


def load_default_rubric() -> Rubric:
    return Rubric.model_validate_json(Path(DEFAULT_RUBRIC_PATH).read_text())


def load_default_job_description() -> str:
    path = Path(DEFAULT_JD_PATH)
    return path.read_text() if path.exists() else "No job description provided."
