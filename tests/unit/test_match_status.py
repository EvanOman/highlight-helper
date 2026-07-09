"""Tests for the view-layer match-status and confidence-honesty helpers.

The span locator (``app.services.text_matching``) reports a native
``match_status`` on every ``ExtractedHighlight`` (exact | normalized | fuzzy |
not_found). These helpers translate it into the editor's UI vocabulary and
grade the confidence badge; they must never re-derive status heuristically.
"""

from app.api.views.highlight_views import _display_confidence, _ui_match_status
from app.services.highlight_extractor import ExtractedHighlight

FULL_TEXT = "The quick brown fox jumps over the lazy dog. Birds sang softly."


def _result(
    match_status: str,
    *,
    highlight_text: str = "quick brown fox",
    confidence: str = "high",
    highlight_start: int = 4,
    highlight_end: int = 19,
    match_quality: float = 1.0,
) -> ExtractedHighlight:
    return ExtractedHighlight(
        full_text=FULL_TEXT,
        highlight_text=highlight_text,
        confidence=confidence,
        highlight_start=highlight_start,
        highlight_end=highlight_end,
        match_status=match_status,
        match_quality=match_quality,
    )


class TestUiMatchStatus:
    def test_exact_passes_through(self):
        assert _ui_match_status(_result("exact")) == "exact"

    def test_normalized_passes_through(self):
        # normalized is a located span (quality 1.0) — it still pre-selects.
        assert _ui_match_status(_result("normalized")) == "normalized"

    def test_fuzzy_passes_through(self):
        assert _ui_match_status(_result("fuzzy", match_quality=0.8)) == "fuzzy"

    def test_not_found_becomes_failed(self):
        # not_found carries the (0, 0) sentinel span and must never pre-select.
        result = _result(
            "not_found",
            highlight_text="text that is not on the page",
            highlight_start=0,
            highlight_end=0,
            match_quality=0.0,
        )
        assert _ui_match_status(result) == "failed"

    def test_missing_status_defaults_to_failed(self):
        # A result with the field left at its default (not_found) is failed.
        assert _ui_match_status(ExtractedHighlight(full_text=FULL_TEXT)) == "failed"


class TestDisplayConfidence:
    def test_exact_match_passes_confidence_through(self):
        assert _display_confidence("high", "exact") == "high"
        assert _display_confidence("medium", "exact") == "medium"
        assert _display_confidence("low", "exact") == "low"

    def test_normalized_match_caps_high_at_medium(self):
        # Only a verbatim exact hit earns green; normalized caps at yellow.
        assert _display_confidence("high", "normalized") == "medium"
        assert _display_confidence("low", "normalized") == "low"

    def test_fuzzy_match_caps_high_at_medium(self):
        assert _display_confidence("high", "fuzzy") == "medium"

    def test_fuzzy_match_keeps_lower_confidence(self):
        assert _display_confidence("medium", "fuzzy") == "medium"
        assert _display_confidence("low", "fuzzy") == "low"

    def test_failed_match_shows_no_badge(self):
        assert _display_confidence("high", "failed") == ""
        assert _display_confidence("low", "failed") == ""
