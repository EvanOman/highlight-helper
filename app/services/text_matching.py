"""Locate a highlight within full page text, reporting honest match quality.

The public entry point is :func:`locate_highlight`, which returns a
:class:`MatchResult` with character offsets into the *original* ``full_text``
plus an explicit status:

- ``EXACT``: the highlight is a verbatim substring (first occurrence).
- ``NORMALIZED``: it matches after normalization (case, curly quotes, unicode
  dashes, whitespace runs, hyphenated line breaks, accents/ligatures); first
  occurrence in normalized space.
- ``FUZZY``: the best-scoring aligned window passed the quality threshold
  (earliest window wins ties).
- ``NOT_FOUND``: nothing scored above the threshold. Offsets are the (0, 0)
  sentinel — a whole-page span is never fabricated.
"""

from __future__ import annotations

import difflib
import unicodedata
from dataclasses import dataclass
from enum import Enum

# Minimum similarity (SequenceMatcher ratio in normalized space) for a fuzzy
# match to be reported at all; below this the result is NOT_FOUND.
FUZZY_QUALITY_THRESHOLD = 0.65

_SOFT_HYPHEN = "\u00ad"  # soft hyphen

# Characters that indicate a word-splitting hyphen at a line break (an em/en
# dash before a newline is punctuation, not hyphenation, so it never rejoins).
_JOINING_HYPHENS = "-\u2010\u2011"  # ascii hyphen, unicode hyphen, non-breaking hyphen

_QUOTE_MAP = {
    "\u2018": "'",  # left single quote
    "\u2019": "'",  # right single quote / apostrophe
    "\u201a": "'",  # single low-9 quote
    "\u201b": "'",  # single high-reversed-9 quote
    "\u2032": "'",  # prime
    "\u201c": '"',  # left double quote
    "\u201d": '"',  # right double quote
    "\u201e": '"',  # double low-9 quote
    "\u201f": '"',  # double high-reversed-9 quote
    "\u2033": '"',  # double prime
}

_DASH_CHARS = frozenset(
    {
        "\u2010",  # hyphen
        "\u2011",  # non-breaking hyphen
        "\u2012",  # figure dash
        "\u2013",  # en dash
        "\u2014",  # em dash
        "\u2015",  # horizontal bar
        "\u2212",  # minus sign
    }
)


class MatchStatus(str, Enum):
    """How (or whether) the highlight was located within the full text."""

    EXACT = "exact"
    NORMALIZED = "normalized"
    FUZZY = "fuzzy"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class MatchResult:
    """Result of locating a highlight within full text.

    ``start``/``end`` are character offsets into the ORIGINAL ``full_text``.
    On ``NOT_FOUND`` they are the (0, 0) sentinel and must not be rendered as
    a selection.
    """

    start: int
    end: int
    status: MatchStatus
    quality: float


_NOT_FOUND = MatchResult(start=0, end=0, status=MatchStatus.NOT_FOUND, quality=0.0)


def locate_highlight(full_text: str, highlight_text: str) -> MatchResult:
    """Locate ``highlight_text`` within ``full_text``.

    Tries, in order: exact substring, normalized match (case/quotes/dashes/
    whitespace/hyphenation-insensitive, with offsets mapped back to the
    original text), then windowed fuzzy alignment. Returns ``NOT_FOUND``
    rather than guessing when nothing scores above
    :data:`FUZZY_QUALITY_THRESHOLD`.
    """
    if not full_text or not highlight_text:
        return _NOT_FOUND

    idx = full_text.find(highlight_text)
    if idx != -1:
        return MatchResult(
            start=idx, end=idx + len(highlight_text), status=MatchStatus.EXACT, quality=1.0
        )

    norm_hay, hay_map = _normalize(full_text)
    norm_needle, _ = _normalize(highlight_text)
    norm_needle = norm_needle.strip()
    if not norm_hay or not norm_needle:
        return _NOT_FOUND

    pos = norm_hay.find(norm_needle)
    if pos != -1:
        start, end = _to_original_span(pos, pos + len(norm_needle), hay_map)
        return MatchResult(start=start, end=end, status=MatchStatus.NORMALIZED, quality=1.0)

    return _fuzzy_locate(norm_hay, hay_map, norm_needle)


def _normalize(text: str) -> tuple[str, list[int]]:
    """Normalize ``text``, keeping a map from normalized to original offsets.

    Applied rules: NFKD decomposition with combining marks stripped (folds
    accents and ligatures like "ﬁ" -> "fi"), casefolding, curly quotes ->
    straight, unicode dashes -> "-", soft hyphens removed (with any line break
    they precede), whitespace runs collapsed to a single space, and hyphenated
    line breaks ("xxx-\\n" + lowercase continuation) rejoined.

    Returns the normalized string and a list where entry ``i`` is the offset
    in ``text`` of the character that produced normalized character ``i``.
    """
    # Stage 1: per-character expansion. Each produced character remembers the
    # offset of the original character it came from.
    expanded: list[tuple[str, int]] = []
    for i, ch in enumerate(text):
        if ch == _SOFT_HYPHEN or ch.isspace():
            expanded.append((ch, i))
            continue
        for decomposed in unicodedata.normalize("NFKD", ch):
            if unicodedata.category(decomposed) == "Mn":
                continue
            mapped = _QUOTE_MAP.get(decomposed, decomposed)
            if mapped in _DASH_CHARS:
                mapped = "-"
            expanded.extend((folded, i) for folded in mapped.casefold())

    # Stage 2: collapse whitespace, drop soft hyphens, rejoin hyphenated line
    # breaks. Case checks use the ORIGINAL character (stage 1 lowercased all).
    out: list[str] = []
    out_map: list[int] = []
    n = len(expanded)
    k = 0
    while k < n:
        ch, orig_idx = expanded[k]

        if ch == _SOFT_HYPHEN:
            # Invisible hyphenation hint: drop it, and if it sits at a line
            # break, swallow the break too so the split word rejoins.
            j = k + 1
            saw_newline = False
            while j < n and expanded[j][0] != _SOFT_HYPHEN and expanded[j][0].isspace():
                if expanded[j][0] in "\r\n":
                    saw_newline = True
                j += 1
            k = j if saw_newline else k + 1
            continue

        if ch.isspace():
            j = k
            saw_newline = False
            while j < n and expanded[j][0].isspace():
                if expanded[j][0] in "\r\n":
                    saw_newline = True
                j += 1
            hyphen_at_line_break = (
                saw_newline
                and j < n
                and len(out) >= 2
                and out[-1] == "-"
                and text[out_map[-1]] in _JOINING_HYPHENS
                and out[-2].isalnum()
                and text[expanded[j][1]].isalnum()
            )
            if hyphen_at_line_break and text[expanded[j][1]].islower():
                # Hyphenated line break ("beau-\ntiful"): drop the hyphen and
                # the break so the word reads joined.
                out.pop()
                out_map.pop()
            elif hyphen_at_line_break:
                # Compound word split at an existing hyphen ("Smith-\nJones"):
                # keep the hyphen but swallow the break.
                pass
            elif out:
                out.append(" ")
                out_map.append(orig_idx)
            # Leading whitespace is dropped entirely (no `else`).
            k = j
            continue

        out.append(ch)
        out_map.append(orig_idx)
        k += 1

    return "".join(out), out_map


def _to_original_span(norm_start: int, norm_end: int, hay_map: list[int]) -> tuple[int, int]:
    """Map a half-open span in normalized space back to original offsets."""
    start = hay_map[norm_start]
    end = hay_map[norm_end - 1] + 1
    return start, end


def _fuzzy_locate(norm_hay: str, hay_map: list[int], norm_needle: str) -> MatchResult:
    """Find the best-scoring window of ``norm_hay`` aligned to ``norm_needle``."""
    window_len = len(norm_needle)

    # Candidate windows begin at word starts so alignment isn't wasted on
    # mid-word offsets.
    starts = [0] + [i + 1 for i, ch in enumerate(norm_hay) if ch == " " and i + 1 < len(norm_hay)]

    matcher = difflib.SequenceMatcher(autojunk=False)
    matcher.set_seq2(norm_needle)
    best_score = 0.0
    best_start = 0
    for s in starts:
        matcher.set_seq1(norm_hay[s : s + window_len])
        if matcher.real_quick_ratio() <= best_score or matcher.quick_ratio() <= best_score:
            continue
        score = matcher.ratio()
        if score > best_score:  # strict '>' keeps the earliest window on ties
            best_score = score
            best_start = s

    if best_score == 0.0:
        return _NOT_FOUND

    # Re-align within a padded region around the best window so the reported
    # span can shed noise at the edges (or pick up truncated tail characters).
    pad = max(10, window_len // 5)
    region_start = max(0, best_start - pad)
    region_end = min(len(norm_hay), best_start + window_len + pad)
    region_matcher = difflib.SequenceMatcher(
        None, norm_hay[region_start:region_end], norm_needle, autojunk=False
    )
    blocks = [b for b in region_matcher.get_matching_blocks() if b.size > 0]
    if not blocks:
        return _NOT_FOUND

    def span_quality(candidate: list[difflib.Match]) -> float:
        lo = region_start + candidate[0].a
        hi = region_start + candidate[-1].a + candidate[-1].size
        return difflib.SequenceMatcher(None, norm_hay[lo:hi], norm_needle, autojunk=False).ratio()

    # Greedily drop stray leading/trailing blocks while doing so improves the
    # score, so `quality` reflects the span actually returned.
    quality = span_quality(blocks)
    while len(blocks) > 1:
        drop_first = span_quality(blocks[1:])
        drop_last = span_quality(blocks[:-1])
        if max(drop_first, drop_last) <= quality:
            break
        if drop_first >= drop_last:
            blocks = blocks[1:]
            quality = drop_first
        else:
            blocks = blocks[:-1]
            quality = drop_last

    if quality < FUZZY_QUALITY_THRESHOLD:
        return _NOT_FOUND

    norm_start = region_start + blocks[0].a
    norm_end = region_start + blocks[-1].a + blocks[-1].size
    start, end = _to_original_span(norm_start, norm_end, hay_map)
    return MatchResult(start=start, end=end, status=MatchStatus.FUZZY, quality=quality)
