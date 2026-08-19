"""Image preparation for the vision model.

Raw PDF page renders (150 DPI PNGs) are far larger than a vision model needs.
We downscale to a bounded long edge and re-encode as JPEG to keep request
payloads (and token cost) small before base64-encoding.
"""
from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

from PIL import Image

from app.config import settings


def resize_for_encoding(
    image_path: str | Path,
    *,
    max_long_edge: int | None = None,
    jpeg_quality: int | None = None,
) -> bytes:
    """Return JPEG bytes for ``image_path``, downscaled and compressed.

    - Long edge is capped at ``max_long_edge`` (never upscales smaller images).
    - Output is baseline JPEG at ``jpeg_quality``.
    - Transparency / palette modes are flattened onto white.
    """
    max_long_edge = max_long_edge or settings.image_max_long_edge_px
    jpeg_quality = jpeg_quality or settings.image_jpeg_quality

    with Image.open(image_path) as img:
        img = _flatten_to_rgb(img)

        long_edge = max(img.width, img.height)
        if long_edge > max_long_edge:
            scale = max_long_edge / long_edge
            new_size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
            img = img.resize(new_size, Image.LANCZOS)

        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=jpeg_quality, optimize=True)
        return buffer.getvalue()


def encode_image_data_url(image_path: str | Path, **kwargs) -> str:
    """Return a ``data:image/jpeg;base64,...`` URL (OpenAI/OpenRouter shape)."""
    jpeg_bytes = resize_for_encoding(image_path, **kwargs)
    b64 = base64.b64encode(jpeg_bytes).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def encode_image_anthropic_block(image_path: str | Path, **kwargs) -> dict:
    """Return an Anthropic-native ``image`` content block for the given image.

    Shape: ``{"type": "image", "source": {"type": "base64",
    "media_type": "image/jpeg", "data": "<b64>"}}`` — distinct from the OpenAI
    ``image_url`` shape so neither SDK's format is forced onto the other.
    """
    jpeg_bytes = resize_for_encoding(image_path, **kwargs)
    b64 = base64.b64encode(jpeg_bytes).decode("ascii")
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
    }


def _flatten_to_rgb(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[-1])
        return background
    if img.mode != "RGB":
        return img.convert("RGB")
    return img
