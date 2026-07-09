"""Tests for the view-layer match-status and confidence-honesty helpers."""

from app.api.views.highlight_views import _derive_match_status, _display_confidence
from app.services.highlight_extractor import ExtractedHighlight

FULL_TEXT = "The quick brown fox jumps over the lazy dog. Birds sang softly."


class _ResultWithNativeStatus(ExtractedHighlight):
    """Simulates a future extractor result that carries a native match_status."""

    match_status: str | None = None


def _result(
    full_text: str = FULL_TEXT,
    highlight_text: str = "quick brown fox",
    confidence: str = "high",
    highlight_start: int = 4,
    highlight_end: int = 19,
) -> ExtractedHighlight:
    return ExtractedHighlight(
        full_text=full_text,
        highlight_text=highlight_text,
        confidence=confidence,
        highlight_start=highlight_start,
        highlight_end=highlight_end,
    )


class TestDeriveMatchStatus:
    def test_exact_substring_is_exact(self):
        assert _derive_match_status(_result()) == "exact"

    def test_whole_page_highlight_is_exact_when_text_matches(self):
        # A highlight that genuinely spans the whole page is still exact.
        result = _result(highlight_text=FULL_TEXT, highlight_start=0, highlight_end=len(FULL_TEXT))
        assert _derive_match_status(result) == "exact"

    def test_whole_page_fallback_is_failed(self):
        # The matcher's failure fallback: offsets span the entire page but the
        # highlight text isn't actually in it.
        result = _result(
            highlight_text="text that is not on the page",
            highlight_start=0,
            highlight_end=len(FULL_TEXT),
        )
        assert _derive_match_status(result) == "failed"

    def test_empty_highlight_is_failed(self):
        assert _derive_match_status(_result(highlight_text="")) == "failed"

    def test_empty_full_text_is_failed(self):
        assert _derive_match_status(_result(full_text="")) == "failed"

    def test_partial_offsets_with_inexact_text_is_fuzzy(self):
        result = _result(
            highlight_text="quick brwon fox",  # OCR noise, not a substring
            highlight_start=4,
            highlight_end=19,
        )
        assert _derive_match_status(result) == "fuzzy"

    def test_native_match_status_takes_precedence(self):
        # Future extractor versions (W2/W3) can attach a native match_status;
        # the helper must let it drop in without re-deriving.
        result = _ResultWithNativeStatus(
            match_status="not_found",
            full_text=FULL_TEXT,
            highlight_text="quick brown fox",  # would derive to "exact" otherwise
            highlight_start=4,
            highlight_end=19,
        )
        assert _derive_match_status(result) == "failed"

    def test_native_normalized_maps_to_exact(self):
        result = _ResultWithNativeStatus(
            match_status="normalized",
            full_text=FULL_TEXT,
            highlight_text="nope",
            highlight_start=0,
            highlight_end=len(FULL_TEXT),
        )
        assert _derive_match_status(result) == "exact"


class TestDisplayConfidence:
    def test_exact_match_passes_confidence_through(self):
        assert _display_confidence("high", "exact") == "high"
        assert _display_confidence("medium", "exact") == "medium"
        assert _display_confidence("low", "exact") == "low"

    def test_fuzzy_match_caps_high_at_medium(self):
        assert _display_confidence("high", "fuzzy") == "medium"

    def test_fuzzy_match_keeps_lower_confidence(self):
        assert _display_confidence("medium", "fuzzy") == "medium"
        assert _display_confidence("low", "fuzzy") == "low"

    def test_failed_match_shows_no_badge(self):
        assert _display_confidence("high", "failed") == ""
        assert _display_confidence("low", "failed") == ""
