#!/usr/bin/env python3
"""CLI for running highlight-extraction evaluations.

Online mode calls the real pipeline (and populates the cache); offline mode
replays genuine cached outputs for CI/smoke. Metrics are always recomputed from
the cached model output, never stored, so offline numbers are honest.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evals.models import EvalReport
from evals.report import generate_html_report, print_summary
from evals.runner import run_evals

_EVALS_DIR = Path(__file__).parent


def _write_json_snapshot(report: EvalReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report.to_json_dict(), f, indent=2, ensure_ascii=False)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run highlight extraction evaluations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m evals.cli                       # online, default 'service' pipeline
  python -m evals.cli --offline             # replay cached outputs (CI/smoke)
  python -m evals.cli --pipeline service    # select a pipeline to A/B
  python -m evals.cli --json-out out.json   # also write a metrics snapshot
        """,
    )
    parser.add_argument("--dataset", type=Path, default=_EVALS_DIR / "samples" / "dataset.json")
    parser.add_argument("--pipeline", default="service", help="Extraction pipeline id")
    parser.add_argument("--offline", action="store_true", help="Replay cached outputs (no API)")
    parser.add_argument("--cache", type=Path, default=None, help="Cache file path")
    parser.add_argument("--report-path", type=Path, default=_EVALS_DIR / "reports" / "latest.html")
    parser.add_argument("--json-out", type=Path, default=None, help="Write a JSON metrics snapshot")
    parser.add_argument("--no-report", action="store_true", help="Skip the HTML report")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    if not args.dataset.exists():
        print(f"Error: dataset not found at {args.dataset}", file=sys.stderr)
        return 1

    print(
        f"Running {args.pipeline} pipeline ({'offline' if args.offline else 'online'}) "
        f"on {args.dataset}"
    )

    report = run_evals(
        dataset_path=args.dataset,
        pipeline_id=args.pipeline,
        offline=args.offline,
        cache_path=args.cache,
        verbose=args.verbose,
    )

    print_summary(report)

    if not args.no_report:
        generate_html_report(report, args.report_path)
        print(f"HTML report: {args.report_path}")

    if args.json_out:
        _write_json_snapshot(report, args.json_out)
        print(f"JSON snapshot: {args.json_out}")

    if report.error_cases:
        print(f"\n{report.error_cases} case(s) errored.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
