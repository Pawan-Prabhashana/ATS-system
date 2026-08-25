"""Google Forms intake: read responses from the linked Sheet, pull CVs from Drive.

Real implementation using ``google-api-python-client`` + ``google-auth``.

Everything credential- or network-related is done **lazily inside the methods**:
importing this module and constructing ``GoogleFormsIntakeSource()`` never
require env vars, credential files, or even the Google client libraries to be
installed. Problems surface as ``IntakeConfigError`` only when a method runs.

To swap to a different backend later, this is the only file that changes.
"""
from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

from app.config import (
    get_google_service_account_file,
    get_google_sheet_id,
)
from app.intake.base import RawSubmission, detect_role_column
from app.intake.errors import IntakeConfigError

# Read-only scopes: form responses live in a Sheet; uploads live in Drive.
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Which sheet range to read. A1 open-ended range covers the whole responses tab.
DEFAULT_RANGE = "A:Z"

# Column-header aliases -> our fields (matched case-insensitively, substring).
_NAME_KEYS = ("name", "full name")
_EMAIL_KEYS = ("email", "e-mail", "email address")
_CV_KEYS = ("cv", "resume", "résumé", "upload", "file")
_TIME_KEYS = ("timestamp", "time", "date")


class GoogleFormsIntakeSource:
    """Fetches submissions from a Google Form's response Sheet + Drive uploads."""

    name = "google_forms"

    def __init__(
        self,
        sheet_id: str | None = None,
        service_account_file: str | None = None,
        sheet_range: str = DEFAULT_RANGE,
    ) -> None:
        # No credentials touched here — construction is always safe. When set,
        # sheet_id / service_account_file OVERRIDE the global env vars (they are
        # wired into fetch/probe in Phase 7B).
        self.sheet_id = sheet_id
        self.service_account_file = service_account_file
        self.sheet_range = sheet_range

    # -- public API -------------------------------------------------------- #
    def fetch_new_submissions(
        self, job_id: str | None = None
    ) -> list[RawSubmission]:
        # One Google Form per opening: this source reads the job's OWN responses
        # sheet (``self.sheet_id``), so its rows belong to ``job_id``. Falls back
        # to the global env only when the instance sheet_id is unset.
        sheet_id = self.sheet_id or get_google_sheet_id()
        if not sheet_id:
            raise IntakeConfigError(
                "No Google Sheet configured. Set the job's google_sheet_id (or "
                "the GOOGLE_SHEET_ID env var) to the form-responses spreadsheet id."
            )
        sheets, _drive = self._build_clients()

        try:
            resp = (
                sheets.spreadsheets()
                .values()
                .get(spreadsheetId=sheet_id, range=self.sheet_range)
                .execute()
            )
        except Exception as exc:  # noqa: BLE001 - surface as config/usage error
            raise IntakeConfigError(f"Failed to read Google Sheet {sheet_id}: {exc}") from exc

        rows = resp.get("values", [])
        if not rows:
            return []

        header = rows[0]
        col = _resolve_columns(header)
        submissions: list[RawSubmission] = []
        for raw in rows[1:]:
            row = _row_to_dict(header, raw)
            cv_cell = _get(row, col["cv"])
            file_id = self._extract_drive_id(cv_cell) if cv_cell else ""
            if not file_id:
                # No usable CV reference -> skip this row (nothing to parse).
                continue
            submissions.append(
                RawSubmission(
                    name=_get(row, col["name"]) or None,
                    email=_get(row, col["email"]) or None,
                    submitted_at=None,  # left to later phases if needed
                    cv_file_ref=file_id,
                    role=_get(row, col.get("role")) or None,
                    raw_row_data=row,
                )
            )
        return submissions

    def probe(self) -> dict:
        """Test the connection to the job's Sheet without ingesting.

        Returns ``{connected, row_count, detected_columns, error}``. NEVER
        raises — any Google/credentials/library problem comes back as
        ``connected: False`` with a human-readable ``error``.
        """
        empty_cols = {"name": None, "email": None, "cv": None, "role": None, "timestamp": None}
        sheet_id = self.sheet_id or get_google_sheet_id()
        if not sheet_id:
            return {
                "connected": False,
                "row_count": 0,
                "role_column_detected": False,
                "detected_columns": empty_cols,
                "distinct_roles": [],
                "error": "No Google Sheet configured (set GOOGLE_SHEET_ID to the form-responses sheet).",
            }
        try:
            sheets, _drive = self._build_clients()
            resp = (
                sheets.spreadsheets()
                .values()
                .get(spreadsheetId=sheet_id, range=self.sheet_range)
                .execute()
            )
        except Exception as exc:  # noqa: BLE001 - report, never raise to a 500
            return {
                "connected": False,
                "row_count": 0,
                "role_column_detected": False,
                "detected_columns": empty_cols,
                "distinct_roles": [],
                "error": str(exc),
            }

        rows = resp.get("values", [])
        if not rows:
            return {
                "connected": True,
                "row_count": 0,
                "role_column_detected": False,
                "detected_columns": empty_cols,
                "distinct_roles": [],
                "error": None,
            }
        header = rows[0]
        cols = _resolve_columns(header)
        role_col = cols.get("role")
        distinct: set[str] = set()
        if role_col:
            for raw in rows[1:]:
                val = _get(_row_to_dict(header, raw), role_col)
                if val:
                    distinct.add(val)
        return {
            "connected": True,
            "row_count": len(rows) - 1,
            "role_column_detected": bool(role_col),
            "detected_columns": {k: cols.get(k) for k in empty_cols},
            "distinct_roles": sorted(distinct),
            "error": None,
        }

    def download_cv_bytes(self, file_id: str) -> bytes:
        """Download a Drive file's bytes IN MEMORY (no disk write) — used by the
        PDF viewer endpoint so CV serving is serverless-safe. Errors surface as
        IntakeConfigError, never a raw exception."""
        _sheets, drive = self._build_clients()
        try:
            from googleapiclient.http import MediaIoBaseDownload

            buf = io.BytesIO()
            downloader = MediaIoBaseDownload(buf, drive.files().get_media(fileId=file_id))
            done = False
            while not done:
                _status, done = downloader.next_chunk()
            return buf.getvalue()
        except IntakeConfigError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise IntakeConfigError(f"Failed to download Drive file {file_id}: {exc}") from exc

    def download_cv(self, submission: RawSubmission, dest_dir: Path) -> Path:
        _sheets, drive = self._build_clients()
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        file_id = submission.cv_file_ref
        try:
            from googleapiclient.http import MediaIoBaseDownload

            meta = drive.files().get(fileId=file_id, fields="name").execute()
            filename = meta.get("name") or f"{file_id}.pdf"
            request = drive.files().get_media(fileId=file_id)

            dest = dest_dir / filename
            with io.FileIO(dest, "wb") as fh:
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    _status, done = downloader.next_chunk()
        except IntakeConfigError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise IntakeConfigError(
                f"Failed to download Drive file {file_id}: {exc}"
            ) from exc
        return dest

    # -- lazy client construction ------------------------------------------ #
    def _build_clients(self) -> tuple[Any, Any]:
        """Load service-account creds and build Sheets + Drive clients.

        All imports are local so the module imports without the Google libs.
        """
        sa_file = self.service_account_file or get_google_service_account_file()
        if not sa_file:
            raise IntakeConfigError(
                "GOOGLE_SERVICE_ACCOUNT_FILE is not set. Point it at your "
                "service-account JSON key to use the Google intake source."
            )
        if not Path(sa_file).exists():
            raise IntakeConfigError(
                f"Service-account file not found: {sa_file}"
            )

        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise IntakeConfigError(
                "Google client libraries are not installed. Install them with "
                "`pip install google-api-python-client google-auth`."
            ) from exc

        try:
            creds = service_account.Credentials.from_service_account_file(
                sa_file, scopes=SCOPES
            )
            sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
            drive = build("drive", "v3", credentials=creds, cache_discovery=False)
        except Exception as exc:  # noqa: BLE001
            raise IntakeConfigError(
                f"Failed to build Google API clients from {sa_file}: {exc}"
            ) from exc
        return sheets, drive

    # -- helpers ----------------------------------------------------------- #
    @staticmethod
    def _extract_drive_id(cell: str) -> str:
        """Parse a Drive file id from a cell that may hold a URL or a bare id."""
        cell = (cell or "").strip()
        if not cell:
            return ""
        # https://drive.google.com/open?id=FILEID
        m = re.search(r"[?&]id=([A-Za-z0-9_-]+)", cell)
        if m:
            return m.group(1)
        # https://drive.google.com/file/d/FILEID/view
        m = re.search(r"/d/([A-Za-z0-9_-]+)", cell)
        if m:
            return m.group(1)
        # Bare id (no slashes / spaces).
        if re.fullmatch(r"[A-Za-z0-9_-]{10,}", cell):
            return cell
        return ""


# --------------------------------------------------------------------------- #
# Row/column helpers
# --------------------------------------------------------------------------- #
def _resolve_columns(header: list[str]) -> dict[str, str | None]:
    def find(keys: tuple[str, ...]) -> str | None:
        for h in header:
            hl = h.strip().lower()
            if any(k in hl for k in keys):
                return h
        return None

    return {
        "name": find(_NAME_KEYS),
        "email": find(_EMAIL_KEYS),
        "cv": find(_CV_KEYS),
        "role": detect_role_column(header),
        "timestamp": find(_TIME_KEYS),
    }


def _row_to_dict(header: list[str], raw: list[str]) -> dict[str, str]:
    return {header[i]: (raw[i] if i < len(raw) else "") for i in range(len(header))}


def _get(row: dict[str, str], key: str | None) -> str:
    if not key:
        return ""
    return (row.get(key) or "").strip()
