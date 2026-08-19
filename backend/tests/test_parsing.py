"""Tests for the parsing pipeline."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.models import ParsedCV, TextExtractionQuality
from app.parsing import parse_cv_file


def test_text_cv_extracts_text_and_images(text_cv_path: Path, output_root: Path):
    candidate, parsed = parse_cv_file(text_cv_path, output_root=output_root)

    assert isinstance(parsed, ParsedCV)
    # Non-empty text.
    assert parsed.raw_text.strip()
    assert "JANE DOE" in parsed.raw_text
    assert parsed.text_extraction_quality is TextExtractionQuality.ok

    # One image per page, actually written to disk.
    assert parsed.page_count == len(parsed.page_images) == 2
    for page_image in parsed.page_images:
        assert Path(page_image.image_path).exists()
        assert page_image.width > 0 and page_image.height > 0

    # Candidate metadata captured.
    assert candidate.file_hash
    assert candidate.cv_filename == text_cv_path.name


def test_scanned_cv_flagged_low(scanned_cv_path: Path, output_root: Path):
    _candidate, parsed = parse_cv_file(scanned_cv_path, output_root=output_root)
    assert parsed.text_extraction_quality is TextExtractionQuality.low
    # Images should still be rendered even when there's no text layer.
    assert parsed.page_images
    assert any("scanned" in w.lower() or "image-only" in w.lower() for w in parsed.parser_warnings)


def test_non_pdf_raises_clean_error(tmp_path: Path, output_root: Path):
    bogus = tmp_path / "not_a_pdf.pdf"
    bogus.write_bytes(b"this is definitely not a pdf")
    with pytest.raises(ValueError):
        parse_cv_file(bogus, output_root=output_root)


def test_missing_file_raises_value_error(output_root: Path):
    with pytest.raises(ValueError):
        parse_cv_file("/nonexistent/does_not_exist.pdf", output_root=output_root)
