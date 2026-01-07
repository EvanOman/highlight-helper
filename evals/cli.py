#!/usr/bin/env python3
"""CLI interface for running highlight extraction evaluations."""

import argparse
import sys
from pathlib import Path

from evals.report import generate_html_report
from evals.runner import run_evals


def main() -> int:
    """Run the evaluation CLI."""
    parser = argparse.ArgumentParser(
        description="Run highlight extraction evaluations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run evals online (calls OpenAI API)
  python -m evals.cli

  # Run evals offline (uses cached results)
  python -m evals.cli --offline

  # Generate report to custom location
  python -m evals.cli --report-path ./my-report.html

  # Use custom dataset
  python -m evals.cli --dataset ./my-dataset.json
        """,
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path(__file__).parent / "samples" / "dataset.json",
        help="Path to the evaluation dataset JSON file",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Run in offline mode using cached results (no API calls)",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=None,
        help="Path to the cache file for offline mode",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=Path(__file__).parent / "reports" / "latest.html",
        help="Path to write the HTML report",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Skip generating HTML report",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print verbose output",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=80.0,
        help="Pass rate threshold percentage (default: 80)",
    )

    args = parser.parse_args()

    # Validate dataset exists
    if not args.dataset.exists():
        print(f"Error: Dataset not found at {args.dataset}", file=sys.stderr)
        return 1

    # Run evaluations
    print(f"Running evaluations from {args.dataset}")
    print(f"Mode: {'offline' if args.offline else 'online'}")
    print()

    report = run_evals(
        dataset_path=args.dataset,
        offline=args.offline,
        cache_path=args.cache,
        verbose=args.verbose,
    )

    # Print summary
    print()
    print("=" * 50)
    print("EVALUATION SUMMARY")
    print("=" * 50)
    print(f"Total cases:    {report.total_cases}")
    print(f"Passed:         {report.passed_cases}")
    print(f"Failed:         {report.failed_cases}")
    print(f"Errors:         {report.error_cases}")
    print(f"Pass rate:      {report.pass_rate:.1f}%")
    print(f"Avg accuracy:   {report.avg_char_accuracy:.1%}")
    print(f"Avg latency:    {report.avg_latency_ms:.0f}ms")
    print("=" * 50)

    # Generate report
    if not args.no_report:
        args.report_path.parent.mkdir(parents=True, exist_ok=True)
        generate_html_report(report, args.report_path)
        print(f"\nHTML report: {args.report_path}")

    # Return exit code based on pass rate
    if report.pass_rate >= args.threshold:
        print(f"\n✓ PASSED (pass rate >= {args.threshold}%)")
        return 0
    else:
        print(f"\n✗ FAILED (pass rate < {args.threshold}%)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
