"""Shared image utility functions for the vision pipeline."""

import io
import logging

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

# Long-edge cap for the image handed to the vision model. Beyond ~1568px common
# vision models gain no extra OCR detail (they tile the image internally), so a
# larger upload only costs latency and bandwidth. Book-page text stays crisply
# legible at this size.
MAX_LONG_EDGE_PX = 1568

# JPEG quality for the re-encode. 88 keeps text edges clean while shrinking
# multi-megabyte phone photos substantially; higher quality inflates bytes with
# no legibility gain for text.
JPEG_QUALITY = 88


def prepare_image_for_vision(image_bytes: bytes) -> bytes:
    """Normalize an uploaded photo for the vision model.

    The steps, in order:

    1. **EXIF orientation** — apply the camera's orientation tag
       (:func:`PIL.ImageOps.exif_transpose`) so a phone photo stored sideways is
       uprighted. This must happen *before* the JPEG re-encode below, which
       strips all metadata; otherwise the orientation hint is lost and the model
       sees a rotated page.
    2. **Downscale** — shrink so the long edge is at most
       :data:`MAX_LONG_EDGE_PX` (never upscale).
    3. **Re-encode as JPEG** — unifies exotic formats (MPO, HEIC, RGBA/P modes)
       and drops metadata, at :data:`JPEG_QUALITY`.

    On any failure the original bytes are returned unchanged — but the failure
    is always logged, so we never silently pass through an un-transposed image.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        # Upright the image per its EXIF orientation before metadata is dropped.
        img = ImageOps.exif_transpose(img)
        if img.mode != "RGB":
            img = img.convert("RGB")

        long_edge = max(img.size)
        if long_edge > MAX_LONG_EDGE_PX:
            scale = MAX_LONG_EDGE_PX / long_edge
            new_size = (
                max(1, round(img.size[0] * scale)),
                max(1, round(img.size[1] * scale)),
            )
            img = img.resize(new_size, Image.Resampling.LANCZOS)

        output = io.BytesIO()
        img.save(output, format="JPEG", quality=JPEG_QUALITY)
        return output.getvalue()
    except Exception:
        logger.warning("Failed to prepare image for vision; using original bytes", exc_info=True)
        return image_bytes


# Backwards-compatible alias: callers that imported the old name keep working.
convert_to_jpeg = prepare_image_for_vision
