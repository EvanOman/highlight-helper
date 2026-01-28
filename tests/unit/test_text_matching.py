"""Unit tests for text matching service."""

from app.services.text_matching import locate_highlight


class TestLocateHighlight:
    """Tests for the locate_highlight function."""

    def test_exact_substring_match(self):
        """Test exact substring match."""
        full = "The quick brown fox jumps over the lazy dog."
        highlight = "brown fox jumps"
        start, end = locate_highlight(full, highlight)
        assert full[start:end] == highlight

    def test_highlight_at_start(self):
        """Test highlight at the start of full text."""
        full = "Beginning of the text and more words follow."
        highlight = "Beginning of the text"
        start, end = locate_highlight(full, highlight)
        assert start == 0
        assert full[start:end] == highlight

    def test_highlight_at_end(self):
        """Test highlight at the end of full text."""
        full = "Some leading text and the important ending."
        highlight = "the important ending."
        start, end = locate_highlight(full, highlight)
        assert end == len(full)
        assert full[start:end] == highlight

    def test_highlight_equals_full_text(self):
        """Test when highlight is the entire full text."""
        text = "This is the complete text."
        start, end = locate_highlight(text, text)
        assert start == 0
        assert end == len(text)

    def test_fuzzy_match_minor_differences(self):
        """Test fuzzy matching with minor OCR differences."""
        full = "The quick brown fox jumps over the lazy dog."
        # Simulate OCR difference: 'jumps' -> 'jump5'
        highlight = "brown fox jump5 over"
        start, end = locate_highlight(full, highlight)
        # Should find approximate region
        assert start <= full.index("brown")
        assert end >= full.index("over") + len("over")

    def test_no_match_returns_full_range(self):
        """Test that no match falls back to selecting everything."""
        full = "The quick brown fox."
        highlight = "completely unrelated text with nothing in common xyz"
        start, end = locate_highlight(full, highlight)
        assert start == 0
        assert end == len(full)

    def test_empty_full_text(self):
        """Test with empty full text."""
        start, end = locate_highlight("", "some highlight")
        assert start == 0
        assert end == 0

    def test_empty_highlight_text(self):
        """Test with empty highlight text."""
        full = "Some text here."
        start, end = locate_highlight(full, "")
        assert start == 0
        assert end == len(full)

    def test_both_empty(self):
        """Test with both texts empty."""
        start, end = locate_highlight("", "")
        assert start == 0
        assert end == 0
