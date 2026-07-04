"""Unit tests for the text matching service."""

from app.services.text_matching import (
    FUZZY_QUALITY_THRESHOLD,
    MatchResult,
    MatchStatus,
    locate_highlight,
)


def assert_not_found(result: MatchResult) -> None:
    """A NOT_FOUND result carries the (0, 0) sentinel, never a whole-page span."""
    assert result.status == MatchStatus.NOT_FOUND
    assert (result.start, result.end) == (0, 0)
    assert result.quality == 0.0


class TestExactMatch:
    """Exact substring matches."""

    def test_exact_substring_match(self):
        full = "The quick brown fox jumps over the lazy dog."
        highlight = "brown fox jumps"
        result = locate_highlight(full, highlight)
        assert result.status == MatchStatus.EXACT
        assert result.quality == 1.0
        assert full[result.start : result.end] == highlight

    def test_highlight_at_start(self):
        full = "Beginning of the text and more words follow."
        highlight = "Beginning of the text"
        result = locate_highlight(full, highlight)
        assert result.status == MatchStatus.EXACT
        assert result.start == 0
        assert full[result.start : result.end] == highlight

    def test_highlight_at_end(self):
        full = "Some leading text and the important ending."
        highlight = "the important ending."
        result = locate_highlight(full, highlight)
        assert result.status == MatchStatus.EXACT
        assert result.end == len(full)
        assert full[result.start : result.end] == highlight

    def test_whole_page_highlight_legitimately_matches(self):
        text = "This is the complete text of a very short page."
        result = locate_highlight(text, text)
        assert result.status == MatchStatus.EXACT
        assert result.quality == 1.0
        assert (result.start, result.end) == (0, len(text))

    def test_repeated_phrase_returns_first_occurrence(self):
        full = "the cat sat on the mat. later, the cat sat on the chair."
        highlight = "the cat sat"
        result = locate_highlight(full, highlight)
        assert result.status == MatchStatus.EXACT
        assert result.start == 0
        assert full[result.start : result.end] == highlight


class TestNormalizedMatch:
    """Matches that require normalization; offsets must map back to the original text."""

    def test_case_difference(self):
        full = "It was the Best of Times, it was the worst of times."
        highlight = "the best of times"
        result = locate_highlight(full, highlight)
        assert result.status == MatchStatus.NORMALIZED
        assert result.quality == 1.0
        assert full[result.start : result.end] == "the Best of Times"

    def test_curly_quotes(self):
        full = "She replied, “I don’t know what you mean.”"
        highlight = '"I don\'t know what you mean."'
        result = locate_highlight(full, highlight)
        assert result.status == MatchStatus.NORMALIZED
        assert full[result.start : result.end] == "“I don’t know what you mean.”"

    def test_em_dash_vs_hyphen(self):
        full = "War—and everything it brings—ended that year."
        highlight = "War-and everything it brings-ended"
        result = locate_highlight(full, highlight)
        assert result.status == MatchStatus.NORMALIZED
        assert full[result.start : result.end] == "War—and everything it brings—ended"

    def test_en_dash(self):
        full = "See pages 10–20 for details."
        highlight = "pages 10-20"
        result = locate_highlight(full, highlight)
        assert result.status == MatchStatus.NORMALIZED
        assert full[result.start : result.end] == "pages 10–20"

    def test_whitespace_and_newline_collapse(self):
        full = "First line of text\ncontinues  with   odd\n\n spacing here."
        highlight = "text continues with odd spacing"
        result = locate_highlight(full, highlight)
        assert result.status == MatchStatus.NORMALIZED
        assert full[result.start : result.end] == "text\ncontinues  with   odd\n\n spacing"

    def test_hyphenated_line_break_rejoin_mid_span(self):
        full = "It was a truly beau-\ntiful morning in June."
        highlight = "a truly beautiful morning"
        result = locate_highlight(full, highlight)
        assert result.status == MatchStatus.NORMALIZED
        assert full[result.start : result.end] == "a truly beau-\ntiful morning"

    def test_hyphenated_line_break_at_span_start(self):
        full = "The view was beau-\ntiful beyond words that day."
        highlight = "beautiful beyond words"
        result = locate_highlight(full, highlight)
        assert result.status == MatchStatus.NORMALIZED
        assert full[result.start : result.end] == "beau-\ntiful beyond words"

    def test_hyphenated_line_break_at_span_end(self):
        full = "Everyone agreed it was beau-\ntiful, even the critics."
        highlight = "agreed it was beautiful"
        result = locate_highlight(full, highlight)
        assert result.status == MatchStatus.NORMALIZED
        assert full[result.start : result.end] == "agreed it was beau-\ntiful"

    def test_hyphen_before_uppercase_is_not_rejoined(self):
        # A line-break hyphen followed by an uppercase letter is not
        # hyphenation (e.g. a compound name), so the hyphen must survive.
        full = "They cited the Smith-\nJones theorem in class."
        highlight = "the Smith-Jones theorem"
        result = locate_highlight(full, highlight)
        assert result.status == MatchStatus.NORMALIZED
        assert full[result.start : result.end] == "the Smith-\nJones theorem"

    def test_soft_hyphen_removed(self):
        full = "It was a beau\u00adtiful day outside."
        highlight = "a beautiful day"
        result = locate_highlight(full, highlight)
        assert result.status == MatchStatus.NORMALIZED
        assert full[result.start : result.end] == "a beau\u00adtiful day"

    def test_soft_hyphen_at_line_break(self):
        full = "It was a beau\u00ad\ntiful day outside."
        highlight = "a beautiful day"
        result = locate_highlight(full, highlight)
        assert result.status == MatchStatus.NORMALIZED
        assert full[result.start : result.end] == "a beau\u00ad\ntiful day"

    def test_accent_difference(self):
        full = "We stopped at the café on the corner."
        highlight = "the cafe on the corner"
        result = locate_highlight(full, highlight)
        assert result.status == MatchStatus.NORMALIZED
        assert full[result.start : result.end] == "the café on the corner"

    def test_ligature_fi(self):
        full = "This was the ﬁnal chapter of the book."
        highlight = "the final chapter"
        result = locate_highlight(full, highlight)
        assert result.status == MatchStatus.NORMALIZED
        assert full[result.start : result.end] == "the ﬁnal chapter"

    def test_normalized_whole_page(self):
        full = "THE ENTIRE PAGE\nIS THE HIGHLIGHT."
        highlight = "the entire page is the highlight."
        result = locate_highlight(full, highlight)
        assert result.status == MatchStatus.NORMALIZED
        assert (result.start, result.end) == (0, len(full))

    def test_repeated_phrase_normalized_returns_first_occurrence(self):
        full = "The Cat Sat here. Later The Cat sat there."
        highlight = "the cat sat"
        result = locate_highlight(full, highlight)
        assert result.status == MatchStatus.NORMALIZED
        assert result.start == 0
        assert full[result.start : result.end] == "The Cat Sat"

    def test_combined_normalizations(self):
        full = "“Well,” she said—slowly—“this is a beau-\ntiful   THING.”"
        highlight = '"well," she said-slowly-"this is a beautiful thing."'
        result = locate_highlight(full, highlight)
        assert result.status == MatchStatus.NORMALIZED
        assert result.start == 0
        assert result.end == len(full)


class TestFuzzyMatch:
    """Fuzzy matches: OCR noise, partial corruption. Quality must be honest."""

    def test_ocr_noise_single_substitution(self):
        full = "The quick brown fox jumps over the lazy dog near the river bank."
        highlight = "brown fox jump5 over the lazy dog"  # OCR: s -> 5
        result = locate_highlight(full, highlight)
        assert result.status == MatchStatus.FUZZY
        assert FUZZY_QUALITY_THRESHOLD <= result.quality < 1.0
        matched = full[result.start : result.end]
        assert "fox" in matched
        assert "lazy dog" in matched
        assert "river" not in matched

    def test_ocr_noise_multiple_substitutions(self):
        full = (
            "Happiness is not something ready made. It comes from your own "
            "actions, and from nothing else in this world."
        )
        highlight = "It cornes frorn your own act1ons"  # m->rn, i->1
        result = locate_highlight(full, highlight)
        assert result.status == MatchStatus.FUZZY
        assert result.quality >= FUZZY_QUALITY_THRESHOLD
        matched = full[result.start : result.end]
        assert "comes from your own" in matched
        assert "Happiness" not in matched

    def test_fuzzy_repeated_phrase_prefers_best_window(self):
        full = "the dog ran east over the hill. hours later, the dog ran west toward home."
        highlight = "the dog ran w3st"  # noisy copy of the SECOND occurrence
        result = locate_highlight(full, highlight)
        assert result.status == MatchStatus.FUZZY
        matched = full[result.start : result.end]
        assert "west" in matched
        assert "east" not in matched

    def test_fuzzy_quality_reflects_returned_span(self):
        full = "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod."
        highlight = "consectetur adipiscjng elit"
        result = locate_highlight(full, highlight)
        assert result.status == MatchStatus.FUZZY
        matched = full[result.start : result.end]
        # The returned span should hug the target, not bleed across the page.
        assert matched.startswith("consectetur")
        assert "Lorem" not in matched
        assert "eiusmod" not in matched

    def test_fuzzy_with_normalization_differences(self):
        full = "She whispered, “the hard-\nwon truth mátters most.”"
        highlight = '"the hardwon truth matters m0st."'  # OCR o -> 0
        result = locate_highlight(full, highlight)
        assert result.status == MatchStatus.FUZZY
        matched = full[result.start : result.end]
        assert "truth" in matched
        assert "whispered" not in matched


class TestNotFound:
    """NOT_FOUND must be explicit — never a fabricated whole-page span."""

    def test_target_not_on_page(self):
        full = "The quick brown fox jumps over the lazy dog."
        highlight = "completely unrelated text with nothing in common xyz"
        assert_not_found(locate_highlight(full, highlight))

    def test_target_not_on_page_long_page(self):
        full = " ".join(f"word{i} filler sentence keeps going" for i in range(50))
        highlight = "quantum entanglement of subatomic particles in the vacuum"
        assert_not_found(locate_highlight(full, highlight))

    def test_target_longer_than_page(self):
        full = "A short page."
        highlight = (
            "This alleged highlight is far longer than the page itself and "
            "shares essentially no content with it whatsoever, so the matcher "
            "must refuse to guess."
        )
        assert_not_found(locate_highlight(full, highlight))

    def test_empty_full_text(self):
        assert_not_found(locate_highlight("", "some highlight"))

    def test_empty_highlight_text(self):
        assert_not_found(locate_highlight("Some text here.", ""))

    def test_both_empty(self):
        assert_not_found(locate_highlight("", ""))

    def test_whitespace_only_highlight(self):
        assert_not_found(locate_highlight("Some text here.", "  \n\t "))

    def test_near_miss_below_threshold(self):
        full = "alpha beta gamma delta epsilon zeta eta theta."
        highlight = "alpha omega sigma lambda kappa iota."
        result = locate_highlight(full, highlight)
        # Shares one word and some letters, but nowhere near the threshold.
        assert_not_found(result)


class TestOffsetsAlwaysSliceOriginal:
    """Whatever the path, offsets must slice the ORIGINAL text sensibly."""

    def test_slice_bounds_are_valid_across_paths(self):
        cases = [
            ("plain text with a match inside", "a match inside"),
            ("Text WITH case AND  spacing\ndifferences", "text with case and spacing differences"),
            ("noisy tex+ with 0CR errors in the middle of it", "noisy text with OCR errors"),
            ("nothing relevant here at all", "zebra xylophone quartz"),
        ]
        for full, highlight in cases:
            result = locate_highlight(full, highlight)
            assert 0 <= result.start <= result.end <= len(full)
            assert 0.0 <= result.quality <= 1.0
            if result.status == MatchStatus.NOT_FOUND:
                assert (result.start, result.end) == (0, 0)
            else:
                assert full[result.start : result.end].strip()
