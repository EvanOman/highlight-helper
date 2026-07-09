"""Unit tests for the verbatim self-check / repair helper and typed failure.

``_repair_locate`` is the one cheap, deterministic repair the service runs when
the matcher can't locate a highlight: it trims stray edge tokens and re-locates,
never inventing a span. The ``error`` field gives callers a typed failure signal.
"""

from app.services.highlight_extractor import ExtractedHighlight, _repair_locate
from app.services.text_matching import MatchStatus

FULL = (
    "A good sailor learns to read the water for the darker ruffled patches "
    "that mark a coming gust across the bay."
)


class TestRepairLocate:
    def test_recovers_core_when_both_ends_are_garbage(self):
        # Heavy stray tokens on both ends push the whole span below threshold;
        # trimming them recovers the clean core.
        highlight = "wibblewobble fnordplax grznx the darker ruffled patches quxzarffle mmmvvvbbb"
        result = _repair_locate(FULL, highlight)
        assert result is not None
        assert result.status is not MatchStatus.NOT_FOUND
        assert "darker ruffled patches" in FULL[result.start : result.end]

    def test_recovers_core_with_trailing_garbage(self):
        highlight = "the darker ruffled patches zzzqqqwww fnordplax grumbulax wibble"
        result = _repair_locate(FULL, highlight)
        assert result is not None
        assert result.status is not MatchStatus.NOT_FOUND

    def test_returns_none_when_highlight_absent(self):
        # Nothing on the page matches: repair must NOT fabricate a span.
        absent = "completely unrelated sentence about penguins and igloos in antarctica"
        assert _repair_locate(FULL, absent) is None

    def test_returns_none_for_short_highlights(self):
        # Too few words to trim meaningfully; caller keeps the honest NOT_FOUND.
        assert _repair_locate(FULL, "two words") is None


class TestTypedFailure:
    def test_error_defaults_to_none(self):
        # A successful (or blank-page) result has no error.
        assert ExtractedHighlight().error is None
        assert ExtractedHighlight(full_text="hi", highlight_text="hi").error is None

    def test_error_field_roundtrips(self):
        h = ExtractedHighlight(error="boom")
        assert h.error == "boom"
        assert h.model_dump()["error"] == "boom"
