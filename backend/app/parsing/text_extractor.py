"""Text extraction from PDFs using pdfplumber."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

from app.models import PageText


@dataclass
class TextExtractionResult:
    pages: list[PageText] = field(default_factory=list)
    raw_text: str = ""
    page_count: int = 0
    warnings: list[str] = field(default_factory=list)


def extract_text(pdf_path: str | Path) -> TextExtractionResult:
    """Extract per-page and full text from a PDF.

    Raises ``ValueError`` if the file cannot be opened as a PDF; individual
    pages that fail to yield text are tolerated and recorded as warnings.
    """
    pdf_path = Path(pdf_path)
    result = TextExtractionResult()

    try:
        pdf = pdfplumber.open(str(pdf_path))
    except Exception as exc:  # pdfminer/pdfplumber raise a variety of types
        raise ValueError(f"Could not open '{pdf_path.name}' as a PDF: {exc}") from exc

    with pdf:
        result.page_count = len(pdf.pages)
        page_texts: list[str] = []
        for index, page in enumerate(pdf.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception as exc:  # noqa: BLE001 - keep parsing the rest
                text = ""
                result.warnings.append(f"Page {index}: text extraction failed ({exc}).")
            result.pages.append(PageText(page_number=index, text=text))
            page_texts.append(text)

        result.raw_text = "\n".join(page_texts).strip()

    if result.page_count == 0:
        result.warnings.append("PDF contains no pages.")

    return result
