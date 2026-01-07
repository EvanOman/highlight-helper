"""Evaluation runner for highlight extraction."""

import asyncio
import json
import time
from datetime import datetime
from pathlib import Path

from evals.models import EvalCase, EvalReport, EvalResult


def levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate the Levenshtein distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def char_accuracy(expected: str, actual: str) -> float:
    """Calculate character-level accuracy between expected and actual text."""
    if not expected and not actual:
        return 1.0
    if not expected or not actual:
        return 0.0

    # Normalize whitespace
    expected_norm = " ".join(expected.split())
    actual_norm = " ".join(actual.split())

    distance = levenshtein_distance(expected_norm.lower(), actual_norm.lower())
    max_len = max(len(expected_norm), len(actual_norm))

    return 1.0 - (distance / max_len) if max_len > 0 else 1.0


class EvalRunner:
    """Runner for evaluation cases."""

    def __init__(
        self,
        dataset_path: Path | str,
        offline: bool = False,
        cache_path: Path | str | None = None,
    ):
        """
        Initialize the eval runner.

        Args:
            dataset_path: Path to the dataset JSON file
            offline: If True, use cached results instead of calling the API
            cache_path: Path to cache file for offline mode
        """
        self.dataset_path = Path(dataset_path)
        self.offline = offline
        if cache_path:
            self.cache_path = Path(cache_path)
        else:
            self.cache_path = self.dataset_path.parent / "cache.json"
        self.cases: list[EvalCase] = []
        self._cache: dict[str, dict] = {}

    def load_dataset(self) -> None:
        """Load evaluation cases from the dataset file."""
        with open(self.dataset_path) as f:
            data = json.load(f)

        self.cases = [
            EvalCase(
                id=case["id"],
                image_path=case["image_path"],
                instruction=case["instruction"],
                expected_text=case["expected_text"],
                expected_page_number=case.get("expected_page_number"),
                category=case.get("category", "general"),
                description=case.get("description", ""),
            )
            for case in data.get("cases", [])
        ]

    def load_cache(self) -> None:
        """Load cached results for offline mode."""
        if self.cache_path.exists():
            with open(self.cache_path) as f:
                self._cache = json.load(f)

    def save_cache(self) -> None:
        """Save results to cache for future offline runs."""
        with open(self.cache_path, "w") as f:
            json.dump(self._cache, f, indent=2)

    async def _run_extraction(
        self, case: EvalCase, base_path: Path
    ) -> tuple[str, str | None, str, float]:
        """
        Run extraction on a single case.

        Returns:
            Tuple of (extracted_text, page_number, confidence, latency_ms)
        """
        cache_key = f"{case.id}:{case.instruction}"

        if self.offline:
            if cache_key in self._cache:
                cached = self._cache[cache_key]
                return (
                    cached["text"],
                    cached.get("page_number"),
                    cached.get("confidence", "medium"),
                    cached.get("latency_ms", 0.0),
                )
            else:
                # Return empty result for uncached cases in offline mode
                return "", None, "low", 0.0

        # Online mode - call the actual extractor
        from app.services.highlight_extractor import HighlightExtractorService

        extractor = HighlightExtractorService()
        image_bytes = case.load_image_bytes(base_path)

        start_time = time.perf_counter()
        result = await extractor.extract_highlight(
            image_bytes=image_bytes,
            filename=case.image_path,
            instructions=case.instruction,
        )
        latency_ms = (time.perf_counter() - start_time) * 1000

        # Cache the result
        self._cache[cache_key] = {
            "text": result.text,
            "page_number": result.page_number,
            "confidence": result.confidence,
            "latency_ms": latency_ms,
        }

        return result.text, result.page_number, result.confidence, latency_ms

    async def run_case(self, case: EvalCase, base_path: Path) -> EvalResult:
        """Run a single evaluation case."""
        try:
            actual_text, actual_page, confidence, latency = await self._run_extraction(
                case, base_path
            )

            accuracy = char_accuracy(case.expected_text, actual_text)
            exact = case.expected_text.strip().lower() == actual_text.strip().lower()

            return EvalResult(
                case_id=case.id,
                expected_text=case.expected_text,
                actual_text=actual_text,
                expected_page_number=case.expected_page_number,
                actual_page_number=actual_page,
                confidence=confidence,
                exact_match=exact,
                char_accuracy=accuracy,
                latency_ms=latency,
            )
        except Exception as e:
            return EvalResult(
                case_id=case.id,
                expected_text=case.expected_text,
                actual_text="",
                expected_page_number=case.expected_page_number,
                actual_page_number=None,
                confidence="low",
                exact_match=False,
                char_accuracy=0.0,
                latency_ms=0.0,
                error=str(e),
            )

    async def run(self, verbose: bool = False) -> EvalReport:
        """
        Run all evaluation cases and generate a report.

        Args:
            verbose: If True, print progress

        Returns:
            EvalReport with results
        """
        if not self.cases:
            self.load_dataset()

        if self.offline:
            self.load_cache()

        base_path = self.dataset_path.parent
        results: list[EvalResult] = []

        for i, case in enumerate(self.cases):
            if verbose:
                print(f"Running case {i + 1}/{len(self.cases)}: {case.id}")

            result = await self.run_case(case, base_path)
            results.append(result)

            if verbose:
                status = "✓" if result.passed else "✗"
                print(f"  {status} accuracy={result.char_accuracy:.2%}")

        # Save cache for future offline runs
        if not self.offline:
            self.save_cache()

        # Calculate summary stats
        passed = sum(1 for r in results if r.passed)
        failed = sum(1 for r in results if not r.passed and not r.error)
        errors = sum(1 for r in results if r.error)
        avg_accuracy = sum(r.char_accuracy for r in results) / len(results) if results else 0
        avg_latency = sum(r.latency_ms for r in results) / len(results) if results else 0

        return EvalReport(
            timestamp=datetime.now(),
            total_cases=len(results),
            passed_cases=passed,
            failed_cases=failed,
            error_cases=errors,
            avg_char_accuracy=avg_accuracy,
            avg_latency_ms=avg_latency,
            results=results,
            mode="offline" if self.offline else "online",
        )


def run_evals(
    dataset_path: str | Path,
    offline: bool = False,
    cache_path: str | Path | None = None,
    verbose: bool = False,
) -> EvalReport:
    """
    Convenience function to run evaluations.

    Args:
        dataset_path: Path to the dataset JSON file
        offline: If True, use cached results
        cache_path: Path to cache file
        verbose: If True, print progress

    Returns:
        EvalReport with results
    """
    runner = EvalRunner(dataset_path, offline=offline, cache_path=cache_path)
    return asyncio.run(runner.run(verbose=verbose))
