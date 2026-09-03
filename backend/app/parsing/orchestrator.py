"""Parsing orchestrator: PDF bytes/path -> (Candidate, ParsedCV)."""
from __future__ import annotations

import hashlib
from pathlib import Path

from app.config import settings
from app.models import (
    Candidate,
    ParsedCV,
    TextExtractionQuality,
)
from app.parsing.image_renderer import render_pages
from app.parsing.text_extractor import TextExtractionResult, extract_text

PDF_MAGIC = b"%PDF-"


def compute_file_hash(data: bytes) -> str:
    """SHA-256 of the raw PDF bytes (used for dedup in later phases)."""
    return hashlib.sha256(data).hexdigest()


def _looks_like_pdf(data: bytes) -> bool:
    # A valid PDF begins with %PDF- (possibly after a few junk bytes).
    return PDF_MAGIC in data[:1024]


def parse_cv_bytes(
    data: bytes,
    filename: str,
    *,
    candidate_id: str | None = None,
    output_root: Path | None = None,
    render_images: bool = True,
    extract_text_content: bool = True,
) -> tuple[Candidate, ParsedCV]:
    """Parse a CV supplied as raw bytes.

    Persists the PDF and (when ``render_images``) rendered page images under a
    per-candidate output dir. ``render_images=False`` (Phase 16 pdf_direct) skips
    the poppler render entirely — no images are produced. Raises ``ValueError``
    for non-PDF / corrupt input (callers should turn this into a clean 4xx).
    """
    if not data:
        raise ValueError("Empty file: no PDF bytes received.")
    if not _looks_like_pdf(data):
        raise ValueError(
            f"'{filename}' does not look like a PDF (missing %PDF- header)."
        )

    file_hash = compute_file_hash(data)
    candidate_id = candidate_id or file_hash[:16]
    output_root = output_root or settings.output_dir
    candidate_dir = Path(output_root) / candidate_id
    candidate_dir.mkdir(parents=True, exist_ok=True)

    # Persist the original PDF so downstream/vision phases can re-read it.
    pdf_path = candidate_dir / filename
    pdf_path.write_bytes(data)

    return _parse_pdf_at(
        pdf_path=pdf_path,
        filename=filename,
        candidate_id=candidate_id,
        file_hash=file_hash,
        images_dir=candidate_dir / "pages",
        render_images=render_images,
        extract_text_content=extract_text_content,
    )


def parse_cv_file(
    pdf_path: str | Path,
    *,
    candidate_id: str | None = None,
    output_root: Path | None = None,
    render_images: bool = True,
    extract_text_content: bool = True,
) -> tuple[Candidate, ParsedCV]:
    """Parse a CV from a filesystem path (used by the CLI)."""
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise ValueError(f"File not found: {pdf_path}")
    data = pdf_path.read_bytes()
    return parse_cv_bytes(
        data,
        filename=pdf_path.name,
        candidate_id=candidate_id,
        output_root=output_root,
        render_images=render_images,
        extract_text_content=extract_text_content,
    )


def _parse_pdf_at(
    *,
    pdf_path: Path,
    filename: str,
    candidate_id: str,
    file_hash: str,
    images_dir: Path,
    render_images: bool = True,
    extract_text_content: bool = True,
) -> tuple[Candidate, ParsedCV]:
    warnings: list[str] = []

    # 1. Text extraction (hard failure here means the file is unusable). In
    #    pdf_direct mode Claude reads the PDF itself, so we SKIP pdfplumber
    #    entirely — it's the heaviest per-CV memory cost (loads the whole PDF)
    #    and would otherwise pile up over a big pull.
    if extract_text_content:
        text_result = extract_text(pdf_path)
        warnings.extend(text_result.warnings)
    else:
        text_result = TextExtractionResult()

    # 2. Image rendering. A rendering failure should NOT lose the parsed text,
    #    so we degrade gracefully and record a warning instead of crashing.
    #    In pdf_direct mode we skip rendering entirely (no poppler, no images).
    page_images = []
    if render_images:
        try:
            image_result = render_pages(pdf_path, images_dir)
            page_images = image_result.page_images
            warnings.extend(image_result.warnings)
        except RuntimeError as exc:
            # e.g. poppler missing — surface loudly but keep the ParsedCV.
            warnings.append(str(exc))
        except ValueError as exc:
            warnings.append(f"Image rendering skipped: {exc}")

    # 3. Quality flag.
    quality = (
        TextExtractionQuality.low
        if len(text_result.raw_text) < settings.low_text_char_threshold
        else TextExtractionQuality.ok
    )
    if quality is TextExtractionQuality.low:
        warnings.append(
            "Low extracted-text volume: likely a scanned/image-only CV; "
            "vision step should rely on page images."
        )

    parsed = ParsedCV(
        candidate_id=candidate_id,
        raw_text=text_result.raw_text,
        pages=text_result.pages,
        page_images=page_images,
        page_count=text_result.page_count,
        text_extraction_quality=quality,
        parser_warnings=warnings,
    )

    candidate = Candidate(
        id=candidate_id,
        cv_filename=filename,
        file_hash=file_hash,
    )

    return candidate, parsed
