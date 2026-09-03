"""JSON-file candidate store.

Deliberately simple — a single JSON file, whole-file read/rewrite. This is a
placeholder for the Phase 6 Supabase store; because it implements
``CandidateRepository``, swapping it touches only this file + the factory.

Writes are atomic (temp file in the same directory + ``os.replace``) so a
crash mid-write can't truncate or corrupt the existing file.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from app.config import get_candidate_store_path
from app.models import Candidate, CandidateStatus, Evaluation, ParsedCV
from app.store.base import CandidateRecord

# Maps the reviewer decision to the resulting candidate status. "undecided"
# clears the decision back to the post-scoring state.
_DECISION_STATUS = {
    "shortlist": CandidateStatus.shortlisted,
    "reject": CandidateStatus.rejected,
    "undecided": CandidateStatus.scored,
}

SCHEMA_VERSION = 1


class JSONCandidateStore:
    """A ``CandidateRepository`` backed by one JSON file."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else get_candidate_store_path()
        # Serialize read-modify-write mutations so a concurrent (parallel) pull
        # can't lose updates on this single JSON file. The shared store instance
        # is what workers hold, so an instance lock is sufficient.
        self._lock = threading.Lock()

    # -- reads ------------------------------------------------------------- #
    def _load(self) -> dict[str, CandidateRecord]:
        if not self.path.exists():
            return {}
        with self.path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        records = {}
        for raw in data.get("candidates", []):
            record = CandidateRecord.model_validate(raw)
            records[record.candidate.id] = record
        return records

    def get_by_job_and_hash(
        self, job_id: str, file_hash: str
    ) -> Optional[Candidate]:
        for record in self._load().values():
            if (
                record.candidate.job_id == job_id
                and record.candidate.file_hash == file_hash
            ):
                return record.candidate
        return None

    def get(self, candidate_id: str) -> Optional[CandidateRecord]:
        return self._load().get(candidate_id)

    def list_all(self) -> list[CandidateRecord]:
        return list(self._load().values())

    def list_by_job(
        self, job_id: str, status: Optional[CandidateStatus] = None
    ) -> list[CandidateRecord]:
        # In-memory filter — fine at this scale (JSON store, no real indexing).
        out = [r for r in self._load().values() if r.candidate.job_id == job_id]
        if status is not None:
            out = [r for r in out if r.candidate.status == status]
        return out

    # -- writes ------------------------------------------------------------ #
    def upsert(
        self,
        candidate: Candidate,
        parsed_cv: ParsedCV | None,
        evaluation: Optional[Evaluation],
        *,
        artifact_dir: Optional[str] = None,
        cv_file: Optional[str] = None,
        page_image_files: Optional[list[str]] = None,
    ) -> None:
        parsed_artifacts_dir = None
        page_count = 0
        quality = None
        if parsed_cv is not None:
            page_count = parsed_cv.page_count
            quality = parsed_cv.text_extraction_quality.value
            if parsed_cv.page_images:
                parsed_artifacts_dir = str(
                    Path(parsed_cv.page_images[0].image_path).parent.parent
                )

        with self._lock:
            records = self._load()
            records[candidate.id] = CandidateRecord(
                candidate=candidate,
                evaluation=evaluation,
                parsed_artifacts_dir=parsed_artifacts_dir,
                page_count=page_count,
                text_extraction_quality=quality,
                artifact_dir=artifact_dir,
                cv_file=cv_file,
                page_image_files=page_image_files or [],
            )
            self._write(records)

    def update_status(self, candidate_id: str, status: CandidateStatus) -> None:
        with self._lock:
            records = self._load()
            record = records.get(candidate_id)
            if record is None:
                raise KeyError(f"No candidate with id {candidate_id!r}")
            record.candidate.status = status
            self._write(records)

    def update_decision(
        self,
        candidate_id: str,
        decision: str,
        note: Optional[str],
        decided_by: Optional[str] = None,
    ) -> CandidateRecord:
        status = _DECISION_STATUS.get(decision)
        if status is None:
            raise ValueError(
                f"Invalid decision {decision!r}; expected 'shortlist', 'reject', "
                "or 'undecided'."
            )
        with self._lock:
            records = self._load()
            record = records.get(candidate_id)
            if record is None:
                raise KeyError(f"No candidate with id {candidate_id!r}")

            record.candidate.status = status
            if decision == "undecided":
                # Clean undo — wipe the decision metadata + attribution too.
                record.candidate.reviewer_note = None
                record.candidate.decided_at = None
                record.candidate.decided_by = None
            else:
                record.candidate.reviewer_note = note
                record.candidate.decided_at = datetime.now(timezone.utc)
                record.candidate.decided_by = decided_by
            self._write(records)
            return record

    def record_assignment_sent(
        self,
        candidate_id: str,
        sent_at: datetime,
        deadline: date,
        sent_by: Optional[str] = None,
    ) -> CandidateRecord:
        with self._lock:
            records = self._load()
            record = records.get(candidate_id)
            if record is None:
                raise KeyError(f"No candidate with id {candidate_id!r}")

            record.candidate.status = CandidateStatus.assignment_sent
            record.candidate.assignment_sent_at = sent_at
            record.candidate.assignment_deadline = deadline
            record.candidate.assignment_sent_count += 1
            if sent_by:
                record.candidate.assignment_sent_by = sent_by
            self._write(records)
            return record

    # -- persistence ------------------------------------------------------- #
    def _write(self, records: dict[str, CandidateRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "candidates": [r.model_dump(mode="json") for r in records.values()],
        }
        # Write to a temp file in the same dir, then atomically replace.
        fd, tmp_name = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=".candidates-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, self.path)
        except BaseException:
            # Clean up the temp file on any failure; leave the original intact.
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
            raise
