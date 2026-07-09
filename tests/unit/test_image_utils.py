"""Unit tests for the vision image-preprocessing pipeline.

Covers EXIF orientation transpose (phone photos stored sideways), long-edge
downscaling (no upscale), exotic-mode handling, and the logged failure
passthrough. The eval images are already small and un-rotated, so these
synthetic cases are where the preprocessing behaviour is actually proven.
"""

import io

import pytest
from PIL import Image

from app.services.image_utils import (
    JPEG_QUALITY,
    MAX_LONG_EDGE_PX,
    convert_to_jpeg,
    prepare_image_for_vision,
)


def _jpeg_with_orientation(size: tuple[int, int], orientation: int) -> bytes:
    """Encode a solid image carrying the given EXIF orientation tag."""
    img = Image.new("RGB", size, (200, 120, 60))
    exif = img.getexif()
    exif[274] = orientation  # 0x0112 = Orientation
    out = io.BytesIO()
    img.save(out, format="JPEG", exif=exif.tobytes())
    return out.getvalue()


def _open(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def test_exif_orientation_6_transposes_dimensions():
    # Orientation 6 ("rotate 90") means a stored 60x40 landscape should display
    # as 40x60 portrait. exif_transpose must swap the dimensions.
    raw = _jpeg_with_orientation((60, 40), orientation=6)
    out = prepare_image_for_vision(raw)
    assert _open(out).size == (40, 60)


def test_exif_orientation_1_leaves_dimensions():
    # Orientation 1 is "no rotation": dimensions unchanged.
    raw = _jpeg_with_orientation((60, 40), orientation=1)
    out = prepare_image_for_vision(raw)
    assert _open(out).size == (60, 40)


def test_output_strips_exif_orientation():
    # After transposing, the re-encoded JPEG must not carry a stale orientation
    # tag (which would double-rotate downstream).
    raw = _jpeg_with_orientation((60, 40), orientation=6)
    out = prepare_image_for_vision(raw)
    assert _open(out).getexif().get(274) in (None, 1)


def test_downscales_long_edge():
    img = Image.new("RGB", (3000, 2000), (255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    out = prepare_image_for_vision(buf.getvalue())
    w, h = _open(out).size
    assert max(w, h) == MAX_LONG_EDGE_PX
    # Aspect ratio preserved (3:2).
    assert abs((w / h) - 1.5) < 0.01


def test_does_not_upscale_small_images():
    img = Image.new("RGB", (500, 400), (255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    out = prepare_image_for_vision(buf.getvalue())
    assert _open(out).size == (500, 400)


def test_converts_rgba_to_rgb_jpeg():
    img = Image.new("RGBA", (80, 80), (10, 20, 30, 128))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    out = prepare_image_for_vision(buf.getvalue())
    result = _open(out)
    assert result.format == "JPEG"
    assert result.mode == "RGB"


def test_invalid_bytes_pass_through_unchanged():
    junk = b"this is definitely not an image"
    assert prepare_image_for_vision(junk) == junk


def test_convert_to_jpeg_is_alias():
    assert convert_to_jpeg is prepare_image_for_vision


@pytest.mark.parametrize("orientation", [1, 3, 6, 8])
def test_all_orientations_round_trip_to_valid_jpeg(orientation):
    raw = _jpeg_with_orientation((70, 50), orientation=orientation)
    out = prepare_image_for_vision(raw)
    assert _open(out).format == "JPEG"
    assert JPEG_QUALITY <= 100  # sanity: quality constant is a percentage
