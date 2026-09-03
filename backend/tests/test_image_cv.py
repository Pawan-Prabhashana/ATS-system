"""Applicants who upload an image (photo/screenshot) instead of a PDF: convert
it to a PDF so it can still be scored, instead of erroring out of the pull."""
from pathlib import Path

import pytest
from PIL import Image

from app.pipeline.ingest import _ensure_pdf


def test_image_is_converted_to_pdf(tmp_path):
    img = tmp_path / "cv_photo.jpg"
    Image.new("RGB", (600, 800), "white").save(img)
    pdf_path, converted = _ensure_pdf(img)
    assert converted is True
    assert pdf_path.read_bytes()[:5] == b"%PDF-"


def test_pdf_is_left_alone(tmp_path):
    pdf = tmp_path / "cv.pdf"
    pdf.write_bytes(b"%PDF-1.4 hello")
    out, converted = _ensure_pdf(pdf)
    assert converted is False and out == pdf


def test_unsupported_file_raises(tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_bytes(b"just text, not a pdf or image")
    with pytest.raises(ValueError):
        _ensure_pdf(bad)
