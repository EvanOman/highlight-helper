"""Unit tests for the additive phone-photo augmentation pass.

The augmentation *math* is what's testable without an API: the placement geometry
must keep the whole page (hence its text) inside the frame, the render must be
byte-deterministic in its seed, and the fit-to-frame shrink must actually shrink
an oversized quad. We also check the ground-truth-inheritance / tag plumbing.
"""

from __future__ import annotations

import io
import random

from PIL import Image

from evals.augment_dataset import (
    FRAME,
    FRAME_MARGIN,
    LEVELS,
    PARENT_IDS,
    _fit_inside,
    _perspective_coeffs,
    augment_image,
    page_placement,
)
from evals.models import EvalCase

PAGE = (1000, 1400)


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def test_placement_keeps_whole_page_inside_frame() -> None:
    """Across every level and many seeds, all four page corners stay within the
    frame margin — no glyph can be clipped by the frame edge."""
    fw, fh = FRAME
    lo_x, hi_x = FRAME_MARGIN, fw - FRAME_MARGIN
    lo_y, hi_y = FRAME_MARGIN, fh - FRAME_MARGIN
    for level in LEVELS.values():
        for s in range(300):
            rng = random.Random(s * 31 + 7)
            quad = page_placement(FRAME, PAGE, level, rng)
            assert len(quad) == 4
            for x, y in quad:
                # tolerance for float rounding in the shrink-to-fit step
                assert lo_x - 1e-6 <= x <= hi_x + 1e-6
                assert lo_y - 1e-6 <= y <= hi_y + 1e-6


def test_fit_inside_shrinks_oversized_quad() -> None:
    """A quad far larger than the frame is scaled and translated fully inside."""
    fw, fh = FRAME
    oversized = [
        (-500.0, -500.0),
        (fw + 500.0, -400.0),
        (fw + 600.0, fh + 500.0),
        (-400.0, fh + 300.0),
    ]
    fitted = _fit_inside(list(oversized), fw, fh, FRAME_MARGIN)
    xs = [c[0] for c in fitted]
    ys = [c[1] for c in fitted]
    assert min(xs) >= FRAME_MARGIN - 1e-6
    assert max(xs) <= fw - FRAME_MARGIN + 1e-6
    assert min(ys) >= FRAME_MARGIN - 1e-6
    assert max(ys) <= fh - FRAME_MARGIN + 1e-6


def test_fit_inside_leaves_small_centered_quad_untouched() -> None:
    """A quad already comfortably inside the frame is not moved."""
    quad = [(400.0, 500.0), (800.0, 500.0), (800.0, 1000.0), (400.0, 1000.0)]
    fitted = _fit_inside([tuple(c) for c in quad], FRAME[0], FRAME[1], FRAME_MARGIN)
    assert fitted == [tuple(c) for c in quad]


def test_perspective_coeffs_map_output_corners_to_input() -> None:
    """The solved coefficients send each destination corner to its source corner
    under PIL's projective formula (u = (ax+by+c)/(gx+hy+1), etc.)."""
    src = ((0.0, 0.0), (1000.0, 0.0), (1000.0, 1400.0), (0.0, 1400.0))
    dst = ((120.0, 90.0), (1150.0, 60.0), (1200.0, 1500.0), (60.0, 1450.0))
    a, b, c, d, e, f, g, h = _perspective_coeffs(dst, src)
    for (xd, yd), (xs, ys) in zip(dst, src, strict=True):
        denom = g * xd + h * yd + 1
        assert abs((a * xd + b * yd + c) / denom - xs) < 1e-6
        assert abs((d * xd + e * yd + f) / denom - ys) < 1e-6


def test_augment_image_is_deterministic_in_seed() -> None:
    """Same seed -> identical bytes; different seed -> different bytes."""
    page = Image.new("RGB", (200, 280), (240, 238, 230))
    for level_name in LEVELS:
        first = _png_bytes(augment_image(page, level_name, 4242))
        again = _png_bytes(augment_image(page, level_name, 4242))
        other = _png_bytes(augment_image(page, level_name, 99))
        assert first == again
        assert first != other


def test_augment_image_fills_the_frame() -> None:
    """Output is exactly the frame size regardless of input page size."""
    page = Image.new("RGB", (200, 280), (240, 238, 230))
    out = augment_image(page, "medium", 1)
    assert out.size == FRAME
    assert out.mode == "RGB"


def test_augmentation_tag_added_without_dropping_parent_labels() -> None:
    """An augmented case rolls up under augmentation:{level} AND every parent tag."""
    case = EvalCase.from_dict(
        {
            "id": "sailing-marker-clean-aug-hard",
            "image_path": "sailing-marker-clean-aug-hard.png",
            "instruction": "Extract the highlighted sentence.",
            "full_text": "…",
            "expected_highlight": "…",
            "expected_start": 1,
            "expected_end": 2,
            "modality": "marker",
            "difficulty": "clean",
            "density": "short",
            "parent_id": "sailing-marker-clean",
            "augmentation": "hard",
        }
    )
    assert case.parent_id == "sailing-marker-clean"
    assert "augmentation:hard" in case.tags
    assert "modality:marker" in case.tags
    assert "difficulty:clean" in case.tags
    assert "density:short" in case.tags


def test_original_cases_have_no_augmentation_tag() -> None:
    """The 48 originals lack the augmentation field, so no augmentation tag."""
    case = EvalCase.from_dict(
        {
            "id": "sailing-marker-clean",
            "image_path": "sailing-marker-clean.png",
            "instruction": "x",
            "full_text": "x",
            "expected_highlight": "x",
            "expected_start": 0,
            "expected_end": 1,
        }
    )
    assert case.augmentation is None
    assert not any(t.startswith("augmentation:") for t in case.tags)


def test_parent_ids_are_representative() -> None:
    """The sampled parents cover every axis the augmentation is meant to stress."""
    assert len(PARENT_IDS) == len(set(PARENT_IDS))
    joined = " ".join(PARENT_IDS)
    assert "marker" in joined
    assert "underline" in joined
    assert "instruction" in joined
    assert "negative" in joined
    assert "hyphen" in joined
    assert "repeated" in joined
    # dense coverage: both printing parents are the ~300-word dense page
    assert sum(1 for p in PARENT_IDS if p.startswith("printing-")) >= 2
