"""HTML and terminal reporting for evaluation results.

The HTML report shows the overall metric row, per-category rollups (grouped by
tag axis), and a per-case table. The terminal summary prints the same rollup as
an aligned table. A machine-readable JSON snapshot is written by the CLI.
"""

from __future__ import annotations

import html
from pathlib import Path

from evals.models import EvalReport, MetricSummary

# Charter targets, for at-a-glance colouring only (informational, not a gate).
TARGETS = {
    "highlight_f1": 0.90,
    "span_iou": 0.85,
    "span_located_rate": 0.98,
    "verbatim_rate": 1.00,
    "full_text_cer": 0.05,  # lower is better
    "page_number_accuracy": 0.95,
    "hallucination_rate": 0.0,  # lower is better
}

METRIC_COLUMNS = [
    ("highlight_f1", "Highlight F1", "pct"),
    ("span_iou", "Span IoU", "pct"),
    ("span_located_rate", "Span located", "pct"),
    ("verbatim_rate", "Verbatim", "pct"),
    ("full_text_cer", "Full-text CER", "cer"),
    ("page_number_accuracy", "Page # acc", "pct"),
    ("hallucination_rate", "Halluc.", "cer"),
    ("latency_p50_ms", "Latency p50", "ms"),
    ("cost_per_case_usd", "$/case", "usd"),
]


def _fmt(value: float | None, kind: str) -> str:
    if value is None:
        return "—"
    if kind == "pct":
        return f"{value * 100:.1f}%"
    if kind == "cer":
        return f"{value:.3f}"
    if kind == "ms":
        return f"{value:.0f}ms"
    if kind == "usd":
        return f"${value:.4f}"
    return str(value)


def _rows(summaries: list[MetricSummary]) -> list[list[str]]:
    rows = []
    for s in summaries:
        row = [s.label, str(s.n_cases)]
        for attr, _, kind in METRIC_COLUMNS:
            row.append(_fmt(getattr(s, attr), kind))
        rows.append(row)
    return rows


def print_summary(report: EvalReport) -> None:
    """Print the overall + per-tag rollup as an aligned terminal table."""
    headers = ["Category", "n"] + [label for _, label, _ in METRIC_COLUMNS]
    summaries = [report.overall] + [report.by_tag[k] for k in sorted(report.by_tag)]
    rows = _rows(summaries)

    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt_row(cells: list[str]) -> str:
        return "  ".join(c.ljust(widths[i]) for i, c in enumerate(cells))

    print()
    print("=" * (sum(widths) + 2 * (len(widths) - 1)))
    print(f"EVAL SUMMARY — pipeline={report.pipeline_id} model={report.model} mode={report.mode}")
    print("=" * (sum(widths) + 2 * (len(widths) - 1)))
    print(fmt_row(headers))
    print("-" * (sum(widths) + 2 * (len(widths) - 1)))
    # Overall first (it's summaries[0]), then a blank line, then tags.
    print(fmt_row(rows[0]))
    print("-" * (sum(widths) + 2 * (len(widths) - 1)))
    for row in rows[1:]:
        print(fmt_row(row))
    print("=" * (sum(widths) + 2 * (len(widths) - 1)))
    print(f"Total cost: ${report.total_cost_usd:.4f}   Error cases: {report.error_cases}")
    print()


def _cell_class(attr: str, value: float | None) -> str:
    if value is None or attr not in TARGETS:
        return ""
    target = TARGETS[attr]
    lower_better = attr in ("full_text_cer", "hallucination_rate")
    ok = value <= target if lower_better else value >= target
    return "good" if ok else "bad"


def _summary_table(summaries: list[MetricSummary]) -> str:
    head = "".join(f"<th>{html.escape(label)}</th>" for _, label, _ in METRIC_COLUMNS)
    body_rows = []
    for s in summaries:
        cells = [f"<td class='label'>{html.escape(s.label)}</td>", f"<td>{s.n_cases}</td>"]
        for attr, _, kind in METRIC_COLUMNS:
            value = getattr(s, attr)
            cells.append(f"<td class='{_cell_class(attr, value)}'>{_fmt(value, kind)}</td>")
        body_rows.append(f"<tr>{''.join(cells)}</tr>")
    return f"""
    <table>
      <thead><tr><th>Category</th><th>n</th>{head}</tr></thead>
      <tbody>{"".join(body_rows)}</tbody>
    </table>
    """


def _case_table(report: EvalReport) -> str:
    rows = []
    for r in report.results:
        if r.error:
            status = "<span class='bad'>error</span>"
        elif r.is_negative:
            status = (
                "<span class='bad'>hallucinated</span>"
                if r.hallucinated
                else "<span class='good'>clean</span>"
            )
        else:
            status = f"{(r.highlight_f1 or 0) * 100:.0f}% f1"
        exp = html.escape(r.expected_highlight[:90])
        act = html.escape(r.actual_highlight[:90])
        f1 = _fmt(r.highlight_f1, "pct")
        iou = _fmt(r.span_iou, "pct")
        rows.append(f"""
        <tr>
          <td class='label'>{html.escape(r.case_id)}</td>
          <td>{html.escape(", ".join(r.tags))}</td>
          <td>{status}</td>
          <td>{f1}</td>
          <td>{iou}</td>
          <td>{html.escape(r.match_status)}</td>
          <td>{r.full_text_cer:.3f}</td>
          <td>{r.latency_ms:.0f}ms</td>
          <td title='{html.escape(r.expected_highlight)}'>{exp}</td>
          <td title='{html.escape(r.actual_highlight)}'>{act}</td>
        </tr>
        """)
    return f"""
    <table>
      <thead><tr>
        <th>Case</th><th>Tags</th><th>Status</th><th>F1</th><th>IoU</th>
        <th>Match</th><th>CER</th><th>Latency</th><th>Expected</th><th>Actual</th>
      </tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
    """


def generate_html_report(report: EvalReport, output_path: Path | str) -> None:
    """Write the full HTML report (overall, per-tag rollups, per-case table)."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    tag_summaries = [report.by_tag[k] for k in sorted(report.by_tag)]

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Highlight Extraction Eval — {html.escape(report.pipeline_id)}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: #f8fafc; color: #1e293b; line-height: 1.5; padding: 2rem; }}
  .container {{ max-width: 1400px; margin: 0 auto; }}
  h1 {{ font-size: 1.6rem; margin-bottom: .25rem; }}
  h2 {{ font-size: 1.15rem; margin: 2rem 0 .75rem; }}
  .meta {{ color: #64748b; font-size: .85rem; margin-bottom: 1.5rem; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: .5rem;
          overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.1); font-size: .8rem; margin-bottom: 1rem; }}
  th, td {{ padding: .5rem .6rem; text-align: right; border-bottom: 1px solid #e2e8f0; white-space: nowrap; }}
  th {{ background: #f1f5f9; font-size: .7rem; text-transform: uppercase; letter-spacing: .04em; color: #475569; }}
  td.label, th:first-child {{ text-align: left; font-weight: 600; }}
  td.good {{ color: #15803d; font-weight: 600; }}
  td.bad {{ color: #b91c1c; font-weight: 600; }}
  tr:hover {{ background: #f8fafc; }}
  .scroll {{ overflow-x: auto; }}
</style>
</head>
<body>
<div class="container">
  <h1>Highlight Extraction Eval</h1>
  <p class="meta">
    pipeline <b>{html.escape(report.pipeline_id)}</b> ·
    model <b>{html.escape(report.model)}</b> ·
    mode <b>{html.escape(report.mode)}</b> ·
    {report.timestamp.strftime("%Y-%m-%d %H:%M:%S")} ·
    total cost <b>${report.total_cost_usd:.4f}</b> ·
    errors <b>{report.error_cases}</b>
  </p>

  <h2>Overall</h2>
  <div class="scroll">{_summary_table([report.overall])}</div>

  <h2>By category</h2>
  <div class="scroll">{_summary_table(tag_summaries)}</div>

  <h2>Per case</h2>
  <div class="scroll">{_case_table(report)}</div>
</div>
</body>
</html>
"""
    output_path.write_text(html_content, encoding="utf-8")
