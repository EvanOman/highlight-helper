"""Unit tests for the eval metric math and honest-cache runner.

The metric functions are pure, so they're tested against hand-computed fixtures.
The runner is tested with a fake pipeline (no API): online populates the cache,
offline replays the same genuine output.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.metrics import (
    cer,
    char_span_iou,
    is_verbatim,
    levenshtein_distance,
    normalize_text,
    page_number_matches,
    percentile,
    token_f1,
    tokenize,
)
from evals.models import EvalCase, EvalResult, ExtractionOutput, MetricSummary
from evals.pipelines import build_pipeline
from evals.runner import EvalRunner, _cache_key
from evals.scoring import score_case


class TestNormalize:
    def test_lowercases_and_collapses_whitespace(self):
        assert normalize_text("The   Quick\n Brown") == "the quick brown"

    def test_curly_quotes_and_dashes_folded(self):
        # Curly quotes -> straight, en/em dashes -> hyphen.
        assert normalize_text("“it’s” — a–b") == '"it\'s" - a-b'

    def test_tokenize(self):
        assert tokenize("  Hello,  WORLD  ") == ["hello,", "world"]


class TestTokenF1:
    def test_exact_match_is_one(self):
        assert token_f1("the quick brown fox", "the quick brown fox") == 1.0

    def test_both_empty_is_one(self):
        assert token_f1("", "") == 1.0

    def test_one_empty_is_zero(self):
        assert token_f1("something", "") == 0.0
        assert token_f1("", "something") == 0.0

    def test_partial_overlap(self):
        # expected 4 tokens, actual 4 tokens, 3 shared.
        # precision = recall = 3/4 -> F1 = 0.75
        f1 = token_f1("the quick brown fox", "the quick brown dog")
        assert f1 == pytest.approx(0.75)

    def test_normalization_applied(self):
        assert token_f1("The Quick", "the   quick") == 1.0

    def test_multiset_multiplicity(self):
        # expected has 'the' once; actual twice. shared multiset count = 1.
        # precision = 1/2, recall = 1/1 -> F1 = 2*(.5*1)/(1.5) = 0.6667
        f1 = token_f1("the fox", "the the")
        assert f1 == pytest.approx(2 * (0.5 * 0.5) / (0.5 + 0.5))


class TestCharSpanIoU:
    def test_identical_spans(self):
        assert char_span_iou((10, 20), (10, 20)) == 1.0

    def test_disjoint_spans(self):
        assert char_span_iou((0, 5), (10, 15)) == 0.0

    def test_half_overlap(self):
        # A=[0,10) B=[5,15): inter=5, union=15 -> 1/3
        assert char_span_iou((0, 10), (5, 15)) == pytest.approx(1 / 3)

    def test_both_zero_length_match(self):
        assert char_span_iou((0, 0), (0, 0)) == 1.0

    def test_zero_vs_real_is_zero(self):
        assert char_span_iou((0, 0), (3, 9)) == 0.0


class TestCER:
    def test_perfect(self):
        assert cer("hello world", "hello world") == 0.0

    def test_single_substitution(self):
        # normalized expected len 5 ("hello"), one edit -> 1/5
        assert cer("hello", "hallo") == pytest.approx(1 / 5)

    def test_empty_expected_nonempty_actual(self):
        assert cer("", "junk") == 1.0

    def test_both_empty(self):
        assert cer("", "") == 0.0

    def test_levenshtein_basic(self):
        assert levenshtein_distance("kitten", "sitting") == 3


class TestMisc:
    def test_is_verbatim_true(self):
        assert is_verbatim("Quick Brown", "the quick brown fox") is True

    def test_is_verbatim_false(self):
        assert is_verbatim("purple", "the quick brown fox") is False

    def test_is_verbatim_empty(self):
        assert is_verbatim("", "anything") is False

    def test_is_verbatim_rejoins_hyphenated_line_break(self):
        # "after repair" verbatim: the reading form is verbatim page text even
        # when the page splits the word across a line with a hyphen.
        full = "into a clean bright ell-\nipse, or split a single point of light"
        assert is_verbatim("a clean bright ellipse", full) is True

    def test_is_verbatim_rejects_paraphrase(self):
        # A genuine paraphrase (only a fuzzy match) is NOT verbatim.
        full = "the quick brown fox jumps over the lazy dog"
        assert is_verbatim("a fast auburn fox leaps above the sleepy hound", full) is False

    def test_page_number_matches(self):
        assert page_number_matches("42", "Page 42") is True
        assert page_number_matches("42", "43") is False
        assert page_number_matches(None, "whatever") is True
        assert page_number_matches("42", None) is False

    def test_percentile(self):
        assert percentile([1, 2, 3, 4], 50) == pytest.approx(2.5)
        assert percentile([10], 50) == 10
        assert percentile([], 50) == 0.0


class TestScoring:
    def _case(self, **over) -> EvalCase:
        base = {
            "id": "c1",
            "image_path": "x.png",
            "instruction": "Extract the highlighted sentence.",
            "full_text": "The quick brown fox jumps over the lazy dog.",
            "expected_highlight": "quick brown fox",
            "expected_start": 4,
            "expected_end": 19,
            "expected_page_number": "7",
            "modality": "marker",
            "difficulty": "clean",
            "density": "short",
        }
        base.update(over)
        return EvalCase(**base)  # type: ignore[arg-type]

    def test_perfect_positive(self):
        case = self._case()
        out = ExtractionOutput(
            full_text=case.full_text,
            highlight_text="quick brown fox",
            page_number="7",
            highlight_start=4,
            highlight_end=19,
            match_status="exact",
            match_quality=1.0,
            cost_usd=0.001,
        )
        r = score_case(case, out, latency_ms=100.0)
        assert r.highlight_f1 == 1.0
        assert r.span_iou == 1.0
        assert r.span_located is True
        assert r.verbatim is True
        assert r.full_text_cer == 0.0
        assert r.page_number_correct is True
        assert r.hallucinated is None

    def test_not_found_positive(self):
        case = self._case()
        out = ExtractionOutput(
            full_text=case.full_text,
            highlight_text="",
            match_status="not_found",
        )
        r = score_case(case, out, latency_ms=50.0)
        assert r.span_located is False
        assert r.span_iou == 0.0
        assert r.verbatim is False
        assert r.highlight_f1 == 0.0

    def test_negative_clean(self):
        case = self._case(is_negative=True, expected_highlight="", expected_start=0, expected_end=0)
        out = ExtractionOutput(full_text=case.full_text, highlight_text="")
        r = score_case(case, out, latency_ms=20.0)
        assert r.is_negative is True
        assert r.hallucinated is False
        assert r.highlight_f1 is None
        assert r.span_iou is None

    def test_negative_hallucinated(self):
        case = self._case(is_negative=True, expected_highlight="", expected_start=0, expected_end=0)
        out = ExtractionOutput(full_text=case.full_text, highlight_text="lazy dog")
        r = score_case(case, out, latency_ms=20.0)
        assert r.hallucinated is True

    def test_span_iou_measured_in_ground_truth_coords(self):
        # Extracted highlight is a superset; IoU should be < 1 but > 0.
        case = self._case()
        out = ExtractionOutput(
            full_text=case.full_text,
            highlight_text="the quick brown fox jumps",
            match_status="exact",
        )
        r = score_case(case, out, latency_ms=10.0)
        assert 0.0 < (r.span_iou or 0.0) < 1.0


class TestMetricSummary:
    def test_none_metrics_skipped_and_rates_computed(self):
        results = [
            EvalResult(
                case_id="p1",
                tags=["modality:marker"],
                is_negative=False,
                expected_highlight="a b",
                actual_highlight="a b",
                match_status="exact",
                latency_ms=100.0,
                cost_usd=0.002,
                full_text_cer=0.0,
                highlight_f1=1.0,
                span_iou=1.0,
                span_located=True,
                verbatim=True,
                page_number_correct=True,
            ),
            EvalResult(
                case_id="n1",
                tags=["edge:negative"],
                is_negative=True,
                expected_highlight="",
                actual_highlight="",
                match_status="not_found",
                latency_ms=50.0,
                cost_usd=0.001,
                full_text_cer=0.0,
                hallucinated=False,
                page_number_correct=None,
            ),
        ]
        s = MetricSummary.from_results("overall", results)
        assert s.n_cases == 2
        # F1 averages only the positive case (negative's F1 is None).
        assert s.highlight_f1 == 1.0
        assert s.hallucination_rate == 0.0
        assert s.cost_per_case_usd == pytest.approx(0.0015)
        assert s.latency_p50_ms == pytest.approx(75.0)


class _FakePipeline:
    """Deterministic pipeline for runner tests (no API)."""

    id = "fake"
    model = "fake/model-1"

    async def extract(self, image_bytes, filename, instruction) -> ExtractionOutput:
        return ExtractionOutput(
            full_text="hello world",
            highlight_text="hello",
            page_number="1",
            highlight_start=0,
            highlight_end=5,
            match_status="exact",
            match_quality=1.0,
            cost_usd=0.0007,
        )


def _write_tiny_dataset(tmp_path: Path, image: Path) -> Path:
    dataset = {
        "cases": [
            {
                "id": "t1",
                "image_path": str(image),
                "instruction": "Extract the highlighted text.",
                "full_text": "hello world",
                "expected_highlight": "hello",
                "expected_start": 0,
                "expected_end": 5,
                "expected_page_number": "1",
                "modality": "marker",
                "difficulty": "clean",
                "density": "short",
                "is_negative": False,
            }
        ]
    }
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(dataset), encoding="utf-8")
    return path


def test_cache_key_changes_with_inputs():
    img = b"imagebytes"
    base = _cache_key(img, "m", "p", "instr")
    assert base == _cache_key(img, "m", "p", "instr")  # stable
    assert base != _cache_key(b"other", "m", "p", "instr")
    assert base != _cache_key(img, "m2", "p", "instr")
    assert base != _cache_key(img, "m", "p2", "instr")
    assert base != _cache_key(img, "m", "p", "instr2")


async def test_runner_online_then_offline_replay(tmp_path):
    image = tmp_path / "img.png"
    image.write_bytes(b"\x89PNG-fake-bytes")
    dataset = _write_tiny_dataset(tmp_path, image)
    cache = tmp_path / "cache.json"

    online = EvalRunner(dataset, _FakePipeline(), offline=False, cache_path=cache)
    report = await online.run()
    assert report.mode == "online"
    assert report.error_cases == 0
    assert report.overall.highlight_f1 == 1.0
    assert cache.exists()

    # Cache stores genuine output, not the expected answer.
    cache_data = json.loads(cache.read_text())
    (entry,) = cache_data.values()
    assert entry["output"]["highlight_text"] == "hello"

    offline = EvalRunner(dataset, _FakePipeline(), offline=True, cache_path=cache)
    report2 = await offline.run()
    assert report2.mode == "offline"
    assert report2.error_cases == 0
    assert report2.overall.highlight_f1 == report.overall.highlight_f1


async def test_runner_offline_cache_miss_is_honest(tmp_path):
    image = tmp_path / "img.png"
    image.write_bytes(b"no-cache-for-this")
    dataset = _write_tiny_dataset(tmp_path, image)
    cache = tmp_path / "cache.json"
    cache.write_text("{}", encoding="utf-8")

    offline = EvalRunner(dataset, _FakePipeline(), offline=True, cache_path=cache)
    report = await offline.run()
    # A miss is surfaced as an error, never fabricated as a pass.
    assert report.error_cases == 1


def test_build_pipeline_unknown_raises():
    with pytest.raises(ValueError, match="Unknown pipeline"):
        build_pipeline("does-not-exist")
