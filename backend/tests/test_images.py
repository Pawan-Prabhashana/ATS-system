"""Tests for the image-resize helper used before base64 encoding."""
from __future__ import annotations

import base64

from PIL import Image

from app.evaluation.images import encode_image_data_url, resize_for_encoding


def _make_big_png(path, size=(2000, 2600)):
    Image.new("RGB", size, (200, 210, 220)).save(path, "PNG")
    return path


def test_resize_caps_long_edge(tmp_path):
    src = _make_big_png(tmp_path / "page.png", size=(2000, 2600))
    jpeg_bytes = resize_for_encoding(src, max_long_edge=1200, jpeg_quality=80)

    # Round-trip to check dimensions.
    from io import BytesIO

    with Image.open(BytesIO(jpeg_bytes)) as out:
        assert max(out.size) <= 1200
        assert out.format == "JPEG"


def test_resize_output_under_size_ceiling(tmp_path):
    src = _make_big_png(tmp_path / "page.png", size=(2480, 3508))  # ~A4 @ 300dpi
    jpeg_bytes = resize_for_encoding(src)
    # A downscaled, compressed page should be comfortably small.
    assert len(jpeg_bytes) < 500_000


def test_resize_does_not_upscale(tmp_path):
    src = _make_big_png(tmp_path / "small.png", size=(400, 300))
    jpeg_bytes = resize_for_encoding(src, max_long_edge=1200)
    from io import BytesIO

    with Image.open(BytesIO(jpeg_bytes)) as out:
        assert out.size == (400, 300)


def test_encode_data_url_prefix(tmp_path):
    src = _make_big_png(tmp_path / "page.png")
    url = encode_image_data_url(src)
    assert url.startswith("data:image/jpeg;base64,")
    # Payload decodes cleanly.
    payload = url.split(",", 1)[1]
    assert base64.b64decode(payload)
