"""Pure metric functions for scoring highlight extraction.

Every function here is deterministic and dependency-light so the metric math can
be unit-tested against known fixtures. Text metrics normalize first (lowercase,
straight quotes, unicode dashes -> ``-``, collapsed whitespace) so cosmetic OCR
differences don't count against the pipeline.
"""

from __future__ import annotations

from collections import Counter

_QUOTE_MAP = {
    "‘": "'",
    "’": "'",
    "‚": "'",
    "‛": "'",
    "′": "'",
    "“": '"',
    "”": '"',
    "„": '"',
    "‟": '"',
    "″": '"',
}

_DASH_CHARS = {
    "‐",
    "‑",
    "‒",
    "–",
    "—",
    "―",
    "−",
}


def normalize_text(text: str) -> str:
    """Normalize for comparison: lowercase, straight quotes, ``-`` dashes, single spaces."""
    out: list[str] = []
    for ch in text:
        mapped = _QUOTE_MAP.get(ch, ch)
        if mapped in _DASH_CHARS:
            mapped = "-"
        out.append(mapped)
    collapsed = " ".join("".join(out).split())
    return collapsed.lower()


def tokenize(text: str) -> list[str]:
    """Whitespace tokens of the normalized text."""
    return normalize_text(text).split()


def token_f1(expected: str, actual: str) -> float:
    """Token-level F1 (multiset overlap) of normalized ``expected`` vs ``actual``.

    Both empty -> 1.0 (nothing expected, nothing produced). Exactly one empty ->
    0.0. Otherwise standard precision/recall F1 over the token multiset.
    """
    exp = tokenize(expected)
    act = tokenize(actual)
    if not exp and not act:
        return 1.0
    if not exp or not act:
        return 0.0

    overlap = sum((Counter(exp) & Counter(act)).values())
    if overlap == 0:
        return 0.0
    precision = overlap / len(act)
    recall = overlap / len(exp)
    return 2 * precision * recall / (precision + recall)


def char_span_iou(a: tuple[int, int], b: tuple[int, int]) -> float:
    """Intersection-over-union of two half-open character intervals.

    Two zero-length spans are treated as a perfect match (1.0); a zero-length
    span against a real one is 0.0.
    """
    a0, a1 = a
    b0, b1 = b
    len_a = max(0, a1 - a0)
    len_b = max(0, b1 - b0)
    if len_a == 0 and len_b == 0:
        return 1.0
    if len_a == 0 or len_b == 0:
        return 0.0
    inter = max(0, min(a1, b1) - max(a0, b0))
    union = len_a + len_b - inter
    return inter / union if union > 0 else 0.0


def levenshtein_distance(s1: str, s2: str) -> int:
    """Edit distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if not s2:
        return len(s1)

    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def cer(expected: str, actual: str) -> float:
    """Character error rate of ``actual`` against ``expected`` (normalized).

    CER = edit_distance / len(expected). Both empty -> 0.0; expected empty but
    actual non-empty -> 1.0 (everything produced is spurious).
    """
    exp = normalize_text(expected)
    act = normalize_text(actual)
    if not exp:
        return 0.0 if not act else 1.0
    return levenshtein_distance(exp, act) / len(exp)


def is_verbatim(highlight: str, full_text: str) -> bool:
    """Whether ``highlight`` is verbatim page text *after repair*.

    The charter defines verbatim as "``highlight_text`` is a verbatim substring
    of ``full_text`` after repair" — i.e. after the cosmetic normalization the
    product actually applies when it locates and saves a highlight (case, curly
    quotes, unicode dashes, whitespace, AND hyphenated line-break rejoin). A
    plain substring check misses the hyphen-rejoin step: a highlight that reads
    "beautiful" is genuinely verbatim page text even when the page prints it
    "beau-\\ntiful", because the product rejoins it at save time.

    So verbatimness is measured with the product's own locator: an ``exact`` or
    ``normalized`` match counts as verbatim (the returned text is the page text,
    up to that cosmetic normalization); a merely ``fuzzy`` (approximate) or
    ``not_found`` match does not.
    """
    if not highlight:
        return False
    from app.services.text_matching import MatchStatus, locate_highlight

    status = locate_highlight(full_text, highlight).status
    return status in (MatchStatus.EXACT, MatchStatus.NORMALIZED)


def page_number_matches(expected: str | None, actual: str | None) -> bool:
    """Compare page numbers by their digit runs, tolerating labels like ``Page 42``."""
    if expected is None:
        return True

    def digits(value: str | None) -> str:
        return "".join(c for c in (value or "") if c.isdigit())

    return digits(expected) == digits(actual) and digits(expected) != ""


def percentile(values: list[float], pct: float) -> float:
    """Linear-interpolated percentile (``pct`` in [0, 100]) of ``values``."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (pct / 100.0) * (len(ordered) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    frac = rank - lo
    return ordered[lo] + (ordered[hi] - ordered[lo]) * frac
