"""Offline intake source backed by a CSV fixture.

Reads ``sample_data/mock_form_responses.csv`` (columns: timestamp, name, email,
cv_filename) and resolves each ``cv_filename`` against ``sample_data/``.
Fully offline — no credentials, no network.
"""
from __future__ import annotations

import csv
import shutil
from datetime import datetime
from pathlib import Path

from app.config import settings
from app.intake.base import RawSubmission
from app.intake.errors import IntakeError

DEFAULT_CSV = settings.sample_data_dir / "mock_form_responses.csv"


class LocalFixtureIntakeSource:
    """Reads submissions from a local CSV; copies CVs from disk."""

    name = "local_fixture"

    def __init__(
        self,
        csv_path: str | Path | None = None,
        base_dir: str | Path | None = None,
    ) -> None:
        self.csv_path = Path(csv_path) if csv_path else DEFAULT_CSV
        # Directory the cv_filename column is resolved against.
        self.base_dir = Path(base_dir) if base_dir else settings.sample_data_dir

    def fetch_new_submissions(
        self, job_id: str | None = None
    ) -> list[RawSubmission]:
        if not self.csv_path.exists():
            raise IntakeError(f"Fixture CSV not found: {self.csv_path}")

        submissions: list[RawSubmission] = []
        with self.csv_path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                row_job_id = (row.get("job_id") or "").strip() or None
                submissions.append(
                    RawSubmission(
                        name=(row.get("name") or "").strip() or None,
                        email=(row.get("email") or "").strip() or None,
                        submitted_at=_parse_timestamp(row.get("timestamp")),
                        cv_file_ref=(row.get("cv_filename") or "").strip(),
                        job_id=row_job_id,
                        raw_row_data=dict(row),
                    )
                )
        if job_id is not None:
            submissions = [s for s in submissions if s.job_id == job_id]
        return submissions

    def download_cv(self, submission: RawSubmission, dest_dir: Path) -> Path:
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        src = self.base_dir / submission.cv_file_ref
        if not src.exists():
            raise IntakeError(f"CV file not found for fixture row: {src}")
        dest = dest_dir / src.name
        shutil.copyfile(src, dest)
        return dest


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
