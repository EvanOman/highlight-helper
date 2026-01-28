"""Fuzzy text matching utility for locating highlights within full page text."""

import difflib


def locate_highlight(full_text: str, highlight_text: str) -> tuple[int, int]:
    """Locate highlight_text within full_text, returning character offsets.

    Tries exact substring match first, then falls back to fuzzy matching
    using difflib.SequenceMatcher to handle minor OCR differences.

    Args:
        full_text: The complete page text.
        highlight_text: The highlighted portion to locate.

    Returns:
        Tuple of (char_start, char_end) offsets into full_text.
        Falls back to (0, len(full_text)) if no match is found.
    """
    if not full_text or not highlight_text:
        return (0, len(full_text))

    # Try exact substring match first
    idx = full_text.find(highlight_text)
    if idx != -1:
        return (idx, idx + len(highlight_text))

    # Fall back to fuzzy matching using SequenceMatcher
    matcher = difflib.SequenceMatcher(None, full_text, highlight_text)
    blocks = matcher.get_matching_blocks()

    if not blocks or (len(blocks) == 1 and blocks[0].size == 0):
        return (0, len(full_text))

    # Find the region in full_text that best covers the highlight
    # Use the first and last matching blocks to determine the span
    real_blocks = [b for b in blocks if b.size > 0]
    if not real_blocks:
        return (0, len(full_text))

    start = real_blocks[0].a
    last = real_blocks[-1]
    end = last.a + last.size

    # Only accept the fuzzy match if it covers a reasonable portion
    matched_chars = sum(b.size for b in real_blocks)
    if matched_chars < len(highlight_text) * 0.4:
        return (0, len(full_text))

    return (start, end)
