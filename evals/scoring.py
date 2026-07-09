"""Score a pipeline's :class:`ExtractionOutput` against an :class:`EvalCase`.

Scoring is kept separate from extraction so it is recomputed on every run (even
in offline replay): the cache stores only genuine model outputs, never scores.
"""

from __future__ import annotations

from app.services.text_matching import locate_highlight
from evals.metrics import (
    cer,
    char_span_iou,
    is_verbatim,
    page_number_matches,
    token_f1,
)
from evals.models import EvalCase, EvalResult, ExtractionOutput


def score_case(
    case: EvalCase,
    output: ExtractionOutput,
    latency_ms: float,
    error: str | None = None,
) -> EvalResult:
    """Compute all per-case metrics comparing ``output`` to the ground truth."""
    full_text_cer = cer(case.full_text, output.full_text)

    page_correct: bool | None = None
    if case.expected_page_number is not None:
        page_correct = page_number_matches(case.expected_page_number, output.page_number)

    if case.is_negative:
        # A negative case expects an empty extraction; any highlight is a hallucination.
        hallucinated = bool(output.highlight_text.strip())
        return EvalResult(
            case_id=case.id,
            tags=case.tags,
            is_negative=True,
            expected_highlight="",
            actual_highlight=output.highlight_text,
            match_status=output.match_status,
            latency_ms=latency_ms,
            cost_usd=output.cost_usd,
            full_text_cer=full_text_cer,
            hallucinated=hallucinated,
            page_number_correct=page_correct,
            error=error,
        )

    f1 = token_f1(case.expected_highlight, output.highlight_text)
    verbatim = is_verbatim(output.highlight_text, output.full_text)
    span_located = output.match_status != "not_found"

    # Span IoU is measured in ground-truth coordinates: locate the *extracted*
    # highlight text inside the ground-truth full_text (same matcher the app
    # uses), then compare that span to the known ground-truth span. This is
    # comparable across differing OCR of full_text.
    iou = 0.0
    if output.highlight_text:
        located = locate_highlight(case.full_text, output.highlight_text)
        if located.status.value != "not_found":
            iou = char_span_iou(case.expected_span, (located.start, located.end))

    return EvalResult(
        case_id=case.id,
        tags=case.tags,
        is_negative=False,
        expected_highlight=case.expected_highlight,
        actual_highlight=output.highlight_text,
        match_status=output.match_status,
        latency_ms=latency_ms,
        cost_usd=output.cost_usd,
        full_text_cer=full_text_cer,
        highlight_f1=f1,
        span_iou=iou,
        span_located=span_located,
        verbatim=verbatim,
        page_number_correct=page_correct,
        error=error,
    )
