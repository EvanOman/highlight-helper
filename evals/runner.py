"""Honest evaluation runner for highlight extraction.

The cache is keyed on ``sha256(image) + model + pipeline_id + instruction`` and
only ever stores genuine pipeline outputs (never expected answers). Offline mode
replays that cache; a miss is an honest miss, reported loudly, not fabricated.
Extraction is pluggable via a :class:`~evals.pipelines.Pipeline`, so pipelines
can be A/B'd without editing this runner.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from evals.models import EvalCase, EvalReport, EvalResult, ExtractionOutput, MetricSummary
from evals.pipelines import Pipeline, build_pipeline
from evals.scoring import score_case


def _cache_key(image_bytes: bytes, model: str, pipeline_id: str, instruction: str) -> str:
    """Content-addressed cache key. Changing the image, model, pipeline, or
    instruction changes the key, so stale outputs can never be replayed."""
    image_hash = hashlib.sha256(image_bytes).hexdigest()
    h = hashlib.sha256()
    h.update(image_hash.encode())
    h.update(b"\x00")
    h.update(model.encode())
    h.update(b"\x00")
    h.update(pipeline_id.encode())
    h.update(b"\x00")
    h.update(instruction.encode())
    return h.hexdigest()


class EvalRunner:
    """Runs eval cases through a pipeline (or replays them from cache)."""

    def __init__(
        self,
        dataset_path: Path | str,
        pipeline: Pipeline,
        offline: bool = False,
        cache_path: Path | str | None = None,
        case_filter: str | None = None,
        tag_filter: str | None = None,
    ) -> None:
        self.dataset_path = Path(dataset_path)
        self.pipeline = pipeline
        self.offline = offline
        self.cache_path = (
            Path(cache_path) if cache_path else self.dataset_path.parent / "cache.json"
        )
        # Comma-separated substring filters used to run a cheap subset during
        # iteration (e.g. only the failing categories). None = whole dataset.
        self.case_filter = [s.strip() for s in case_filter.split(",")] if case_filter else None
        self.tag_filter = [s.strip() for s in tag_filter.split(",")] if tag_filter else None
        self.cases: list[EvalCase] = []
        self._cache: dict[str, dict] = {}

    def load_dataset(self) -> None:
        with open(self.dataset_path, encoding="utf-8") as f:
            data = json.load(f)
        cases = [EvalCase.from_dict(c) for c in data.get("cases", [])]
        if self.case_filter:
            cases = [c for c in cases if any(f in c.id for f in self.case_filter)]
        if self.tag_filter:
            cases = [c for c in cases if any(f in tag for f in self.tag_filter for tag in c.tags)]
        self.cases = cases

    def load_cache(self) -> None:
        if self.cache_path.exists():
            with open(self.cache_path, encoding="utf-8") as f:
                self._cache = json.load(f)

    def save_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(self._cache, f, indent=2, sort_keys=True)

    async def _extract(
        self, case: EvalCase, base_path: Path
    ) -> tuple[ExtractionOutput, float, str | None]:
        """Return (output, latency_ms, error). Uses the cache in offline mode
        and populates it in online mode."""
        try:
            image_bytes = case.load_image_bytes(base_path)
        except OSError as e:
            return ExtractionOutput(), 0.0, f"image load failed: {e}"
        key = _cache_key(image_bytes, self.pipeline.model, self.pipeline.id, case.instruction)

        if self.offline:
            entry = self._cache.get(key)
            if entry is None:
                print(
                    f"  ! offline cache MISS for '{case.id}' "
                    f"(key {key[:12]}…) — no genuine output to replay",
                    file=sys.stderr,
                )
                return ExtractionOutput(), 0.0, "offline cache miss"
            return (
                ExtractionOutput.from_dict(entry["output"]),
                entry.get("latency_ms", 0.0),
                None,
            )

        start = time.perf_counter()
        try:
            output = await self.pipeline.extract(image_bytes, case.image_path, case.instruction)
        except Exception as e:  # surface any pipeline failure as a case error, not a crash
            latency_ms = (time.perf_counter() - start) * 1000
            return ExtractionOutput(), latency_ms, str(e)
        latency_ms = (time.perf_counter() - start) * 1000

        self._cache[key] = {
            "case_id": case.id,
            "pipeline_id": self.pipeline.id,
            "model": self.pipeline.model,
            "instruction": case.instruction,
            "latency_ms": latency_ms,
            "output": output.to_dict(),
        }
        return output, latency_ms, None

    async def run_case(self, case: EvalCase, base_path: Path) -> EvalResult:
        output, latency_ms, error = await self._extract(case, base_path)
        return score_case(case, output, latency_ms, error=error)

    async def run(self, verbose: bool = False) -> EvalReport:
        if not self.cases:
            self.load_dataset()
        # Always load the existing cache first. Offline mode replays it; online
        # mode merges fresh outputs into it so running one pipeline (or a
        # filtered subset) never wipes another pipeline's cached entries.
        self.load_cache()

        base_path = self.dataset_path.parent
        results: list[EvalResult] = []
        for i, case in enumerate(self.cases):
            if verbose:
                print(f"[{i + 1}/{len(self.cases)}] {case.id} ({', '.join(case.tags)})")
            result = await self.run_case(case, base_path)
            results.append(result)
            if verbose:
                self._print_case(result)

        if not self.offline:
            self.save_cache()

        return self._build_report(results)

    @staticmethod
    def _print_case(result: EvalResult) -> None:
        if result.error:
            print(f"    ERROR: {result.error}")
            return
        if result.is_negative:
            flag = "HALLUCINATED" if result.hallucinated else "clean"
            print(f"    negative: {flag}  cer={result.full_text_cer:.3f}")
            return
        print(
            f"    f1={result.highlight_f1:.3f} iou={result.span_iou:.3f} "
            f"located={result.span_located} verbatim={result.verbatim} "
            f"cer={result.full_text_cer:.3f} status={result.match_status}"
        )

    def _build_report(self, results: list[EvalResult]) -> EvalReport:
        by_tag_results: dict[str, list[EvalResult]] = defaultdict(list)
        for r in results:
            for tag in r.tags:
                by_tag_results[tag].append(r)

        by_tag = {
            tag: MetricSummary.from_results(tag, tag_results)
            for tag, tag_results in sorted(by_tag_results.items())
        }
        overall = MetricSummary.from_results("overall", results)
        total_cost = sum(r.cost_usd for r in results)
        error_cases = sum(1 for r in results if r.error)

        return EvalReport(
            timestamp=datetime.now(),
            mode="offline" if self.offline else "online",
            pipeline_id=self.pipeline.id,
            model=self.pipeline.model,
            overall=overall,
            by_tag=by_tag,
            results=results,
            total_cost_usd=total_cost,
            error_cases=error_cases,
        )


def run_evals(
    dataset_path: str | Path,
    pipeline_id: str = "service",
    offline: bool = False,
    cache_path: str | Path | None = None,
    verbose: bool = False,
    case_filter: str | None = None,
    tag_filter: str | None = None,
) -> EvalReport:
    """Convenience wrapper: build the pipeline and run the (optionally filtered) dataset."""
    pipeline = build_pipeline(pipeline_id)
    runner = EvalRunner(
        dataset_path,
        pipeline,
        offline=offline,
        cache_path=cache_path,
        case_filter=case_filter,
        tag_filter=tag_filter,
    )
    return asyncio.run(runner.run(verbose=verbose))
