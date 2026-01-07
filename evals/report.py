"""HTML report generator for evaluation results."""

from pathlib import Path

from evals.models import EvalReport


def generate_html_report(report: EvalReport, output_path: Path | str) -> None:
    """
    Generate an HTML report from evaluation results.

    Args:
        report: The evaluation report
        output_path: Path to write the HTML file
    """
    output_path = Path(output_path)

    # Determine overall status color
    if report.pass_rate >= 90:
        status_color = "#22c55e"  # green
        status_text = "Excellent"
    elif report.pass_rate >= 80:
        status_color = "#84cc16"  # lime
        status_text = "Good"
    elif report.pass_rate >= 60:
        status_color = "#eab308"  # yellow
        status_text = "Needs Improvement"
    else:
        status_color = "#ef4444"  # red
        status_text = "Failing"

    # Build results table rows
    result_rows = []
    for r in report.results:
        if r.error:
            row_class = "error"
            status = "❌ Error"
        elif r.passed:
            row_class = "passed"
            status = "✓ Passed"
        else:
            row_class = "failed"
            status = "✗ Failed"

        # Truncate long text
        if len(r.expected_text) > 100:
            expected_display = r.expected_text[:100] + "..."
        else:
            expected_display = r.expected_text
        if len(r.actual_text) > 100:
            actual_display = r.actual_text[:100] + "..."
        else:
            actual_display = r.actual_text

        result_rows.append(f"""
        <tr class="{row_class}">
            <td>{r.case_id}</td>
            <td>{status}</td>
            <td>{r.char_accuracy:.1%}</td>
            <td>{r.confidence}</td>
            <td>{r.latency_ms:.0f}ms</td>
            <td title="{r.expected_text}">{expected_display}</td>
            <td title="{r.actual_text}">{actual_display}</td>
            <td>{r.error or ""}</td>
        </tr>
        """)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Highlight Extraction Eval Report</title>
    <style>
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f8fafc;
            color: #1e293b;
            line-height: 1.6;
            padding: 2rem;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        h1 {{
            font-size: 1.875rem;
            margin-bottom: 0.5rem;
        }}
        .timestamp {{
            color: #64748b;
            font-size: 0.875rem;
            margin-bottom: 2rem;
        }}
        .summary {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }}
        .stat-card {{
            background: white;
            border-radius: 0.5rem;
            padding: 1.5rem;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}
        .stat-card h3 {{
            font-size: 0.875rem;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        .stat-card .value {{
            font-size: 2rem;
            font-weight: 700;
            margin-top: 0.25rem;
        }}
        .status-badge {{
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 9999px;
            font-weight: 600;
            font-size: 0.875rem;
            color: white;
            background: {status_color};
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: white;
            border-radius: 0.5rem;
            overflow: hidden;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}
        th, td {{
            padding: 0.75rem 1rem;
            text-align: left;
            border-bottom: 1px solid #e2e8f0;
        }}
        th {{
            background: #f1f5f9;
            font-weight: 600;
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: #475569;
        }}
        td {{
            font-size: 0.875rem;
        }}
        tr.passed td:first-child {{
            border-left: 3px solid #22c55e;
        }}
        tr.failed td:first-child {{
            border-left: 3px solid #ef4444;
        }}
        tr.error td:first-child {{
            border-left: 3px solid #f97316;
        }}
        tr:hover {{
            background: #f8fafc;
        }}
        .mode-badge {{
            display: inline-block;
            padding: 0.125rem 0.5rem;
            border-radius: 0.25rem;
            font-size: 0.75rem;
            font-weight: 500;
            background: #e2e8f0;
            color: #475569;
            margin-left: 0.5rem;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Highlight Extraction Eval Report <span class="mode-badge">{report.mode}</span></h1>
        <p class="timestamp">Generated: {report.timestamp.strftime("%Y-%m-%d %H:%M:%S")}</p>

        <div class="summary">
            <div class="stat-card">
                <h3>Status</h3>
                <div class="value"><span class="status-badge">{status_text}</span></div>
            </div>
            <div class="stat-card">
                <h3>Pass Rate</h3>
                <div class="value">{report.pass_rate:.1f}%</div>
            </div>
            <div class="stat-card">
                <h3>Total Cases</h3>
                <div class="value">{report.total_cases}</div>
            </div>
            <div class="stat-card">
                <h3>Passed</h3>
                <div class="value" style="color: #22c55e">{report.passed_cases}</div>
            </div>
            <div class="stat-card">
                <h3>Failed</h3>
                <div class="value" style="color: #ef4444">{report.failed_cases}</div>
            </div>
            <div class="stat-card">
                <h3>Errors</h3>
                <div class="value" style="color: #f97316">{report.error_cases}</div>
            </div>
            <div class="stat-card">
                <h3>Avg Accuracy</h3>
                <div class="value">{report.avg_char_accuracy:.1%}</div>
            </div>
            <div class="stat-card">
                <h3>Avg Latency</h3>
                <div class="value">{report.avg_latency_ms:.0f}ms</div>
            </div>
        </div>

        <h2 style="margin-bottom: 1rem;">Results</h2>
        <table>
            <thead>
                <tr>
                    <th>Case ID</th>
                    <th>Status</th>
                    <th>Accuracy</th>
                    <th>Confidence</th>
                    <th>Latency</th>
                    <th>Expected</th>
                    <th>Actual</th>
                    <th>Error</th>
                </tr>
            </thead>
            <tbody>
                {"".join(result_rows)}
            </tbody>
        </table>
    </div>
</body>
</html>
"""

    output_path.write_text(html)
