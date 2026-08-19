"""Render PDF pages to PNG images using pdf2image (poppler)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pdf2image import convert_from_path
from pdf2image.exceptions import PDFInfoNotInstalledError

from app.config import settings
from app.models import PageImage


@dataclass
class ImageRenderResult:
    page_images: list[PageImage] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def render_pages(
    pdf_path: str | Path,
    output_dir: str | Path,
    *,
    dpi: int | None = None,
) -> ImageRenderResult:
    """Render each page of ``pdf_path`` to a PNG under ``output_dir``.

    ``output_dir`` is created if needed. Returns paths + dimensions per page.
    Raises ``RuntimeError`` with a clear message if poppler is not installed,
    and ``ValueError`` if the file is not a usable PDF.
    """
    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    dpi = dpi or settings.render_dpi

    result = ImageRenderResult()

    try:
        images = convert_from_path(str(pdf_path), dpi=dpi)
    except PDFInfoNotInstalledError as exc:
        raise RuntimeError(
            "poppler is not installed or not on PATH. Install poppler-utils "
            "(macOS: `brew install poppler`, Debian/Ubuntu: "
            "`apt-get install poppler-utils`)."
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise ValueError(
            f"Could not render '{pdf_path.name}' to images: {exc}"
        ) from exc

    for index, image in enumerate(images, start=1):
        image_path = output_dir / f"page_{index:03d}.png"
        image.save(image_path, "PNG")
        result.page_images.append(
            PageImage(
                page_number=index,
                image_path=str(image_path),
                width=image.width,
                height=image.height,
            )
        )

    return result
