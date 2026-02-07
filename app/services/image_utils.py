"""Shared image utility functions."""

import io
import logging

from PIL import Image

logger = logging.getLogger(__name__)


def convert_to_jpeg(image_bytes: bytes) -> bytes:
    """Convert image bytes to JPEG format for compatibility.

    Handles formats like MPO, HEIC, etc. that may not be recognized by dspy.Image.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        # Convert to RGB if necessary (handles RGBA, P mode, etc.)
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # Save as JPEG
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=95)
        return output.getvalue()
    except Exception:
        logger.warning("Failed to convert image to JPEG, using original bytes")
        return image_bytes
