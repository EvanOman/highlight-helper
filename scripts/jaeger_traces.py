#!/usr/bin/env python3
"""CLI tool for querying Jaeger traces from the highlight-helper service.

Usage:
    python scripts/jaeger_traces.py recent [--limit N] [--operation OP]
    python scripts/jaeger_traces.py trace TRACE_ID
    python scripts/jaeger_traces.py chat [--limit N]
    python scripts/jaeger_traces.py errors [--limit N]
    python scripts/jaeger_traces.py operations
"""

import argparse
import json
from datetime import datetime
from urllib.request import urlopen

JAEGER_API = "http://localhost:18686/jaeger/api"
SERVICE = "highlight-helper"


def fetch_json(url: str) -> dict:
    """Fetch JSON from a URL."""
    with urlopen(url) as resp:
        return json.loads(resp.read())


def format_duration(us: int) -> str:
    """Format microseconds into human-readable duration."""
    ms = us / 1000
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms / 1000:.1f}s"


def format_timestamp(us: int) -> str:
    """Format microsecond timestamp to human-readable time."""
    return datetime.fromtimestamp(us / 1_000_000).strftime("%H:%M:%S")


def cmd_operations(_args: argparse.Namespace) -> None:
    """List all operations for the service."""
    data = fetch_json(f"{JAEGER_API}/operations?service={SERVICE}")
    ops = data.get("data", [])
    print(f"Operations for {SERVICE}:")
    for op in sorted(ops):
        name = op if isinstance(op, str) else op.get("name", "?")
        print(f"  {name}")


def cmd_recent(args: argparse.Namespace) -> None:
    """List recent traces."""
    url = f"{JAEGER_API}/traces?service={SERVICE}&limit={args.limit}&lookback={args.lookback}"
    if args.operation:
        url += f"&operation={args.operation}"
    data = fetch_json(url)
    traces = data.get("data", [])
    print(f"Found {len(traces)} traces:\n")

    for t in traces:
        tid = t["traceID"]
        spans = t.get("spans", [])
        ops = sorted({s.get("operationName", "?") for s in spans})
        root_span = min(spans, key=lambda s: s.get("startTime", 0))
        dur = max((s.get("duration", 0) for s in spans), default=0)
        ts = format_timestamp(root_span.get("startTime", 0))

        # Filter to interesting ops
        interesting = [o for o in ops if "http send" not in o and "http receive" not in o]
        print(f"  {tid}  {ts}  {format_duration(dur):>8s}  {', '.join(interesting)}")


def cmd_trace(args: argparse.Namespace) -> None:
    """Show detailed trace info."""
    data = fetch_json(f"{JAEGER_API}/traces/{args.trace_id}")
    traces = data.get("data")
    if not traces:
        print(f"Trace {args.trace_id} not found")
        return

    t = traces[0]
    spans = sorted(t.get("spans", []), key=lambda x: x.get("startTime", 0))
    print(f"Trace {t['traceID']} ({len(spans)} spans)\n")

    skip_tags = {
        "otel.library.name",
        "otel.library.version",
        "otel.scope.name",
        "otel.scope.version",
        "telemetry.sdk.language",
        "telemetry.sdk.name",
        "telemetry.sdk.version",
        "service.name",
        "span.kind",
    }

    for s in spans:
        op = s.get("operationName", "?")
        dur = s.get("duration", 0)
        tags = {tag["key"]: tag["value"] for tag in s.get("tags", [])}
        logs = s.get("logs", [])

        # Skip noisy http send/receive spans unless they have errors
        if ("http send" in op or "http receive" in op) and "error" not in str(tags).lower():
            continue

        print(f"--- {op} ({format_duration(dur)}) ---")
        for k, v in sorted(tags.items()):
            if k in skip_tags:
                continue
            if k.startswith(("http.", "net.", "server.", "asgi.")):
                continue
            print(f"  {k}: {v}")
        for log in logs:
            fields = {f["key"]: f["value"] for f in log.get("fields", [])}
            print(f"  LOG: {fields}")
        print()


def cmd_chat(args: argparse.Namespace) -> None:
    """Show recent chat.stream traces with key metrics."""
    url = f"{JAEGER_API}/traces?service={SERVICE}&operation=chat.stream&limit={args.limit}&lookback={args.lookback}"
    data = fetch_json(url)
    traces = data.get("data", [])
    print(f"Found {len(traces)} chat traces:\n")

    if not traces:
        return

    # Header
    print(
        f"  {'Trace ID':<34s} {'Time':>8s} {'Duration':>10s} {'In Tok':>8s} {'Out Tok':>8s} {'Cost':>8s} {'Stop':>12s} {'Model'}"
    )
    print(f"  {'-' * 34} {'-' * 8} {'-' * 10} {'-' * 8} {'-' * 8} {'-' * 8} {'-' * 12} {'-' * 20}")

    for t in traces:
        tid = t["traceID"]
        spans = t.get("spans", [])
        chat_spans = [s for s in spans if s.get("operationName") == "chat.stream"]
        if not chat_spans:
            continue

        cs = chat_spans[0]
        dur = cs.get("duration", 0)
        tags = {tag["key"]: tag["value"] for tag in cs.get("tags", [])}
        ts = format_timestamp(cs.get("startTime", 0))

        in_tok = tags.get("gen_ai.usage.input_tokens", "?")
        out_tok = tags.get("gen_ai.usage.output_tokens", "?")
        cost = tags.get("chat.cost_usd", "?")
        stop = tags.get("gen_ai.response.finish_reasons", "?")
        model = tags.get("gen_ai.request.model", "?")

        # Format cost
        cost_str = f"${float(cost):.2f}" if cost != "?" else "?"

        # Clean up stop reason
        if isinstance(stop, str) and stop.startswith("["):
            stop = stop.strip('[]"')

        print(
            f"  {tid}  {ts:>8s} {format_duration(dur):>10s} {in_tok!s:>8s} {out_tok!s:>8s} {cost_str:>8s} {stop:>12s} {model}"
        )


def cmd_errors(args: argparse.Namespace) -> None:
    """Find traces with errors."""
    url = f"{JAEGER_API}/traces?service={SERVICE}&limit={args.limit}&lookback={args.lookback}&tags=%7B%22error%22%3A%22true%22%7D"
    data = fetch_json(url)
    traces = data.get("data", [])
    print(f"Found {len(traces)} traces with errors:\n")

    for t in traces:
        tid = t["traceID"]
        spans = t.get("spans", [])
        for s in spans:
            tags = {tag["key"]: tag["value"] for tag in s.get("tags", [])}
            if tags.get("error") or tags.get("otel.status_code") == "ERROR":
                op = s.get("operationName", "?")
                dur = s.get("duration", 0)
                ts = format_timestamp(s.get("startTime", 0))
                print(f"  {tid}  {ts}  {format_duration(dur):>8s}  {op}")
                for k, v in sorted(tags.items()):
                    if "error" in k.lower() or "status" in k.lower():
                        print(f"    {k}: {v}")
                print()


def main():
    parser = argparse.ArgumentParser(description="Query Jaeger traces for highlight-helper")
    sub = parser.add_subparsers(dest="command", required=True)

    # recent
    p = sub.add_parser("recent", help="List recent traces")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--operation", type=str, default=None)
    p.add_argument("--lookback", type=str, default="2h")
    p.set_defaults(func=cmd_recent)

    # trace
    p = sub.add_parser("trace", help="Show detailed trace")
    p.add_argument("trace_id", help="Trace ID (full or prefix)")
    p.set_defaults(func=cmd_trace)

    # chat
    p = sub.add_parser("chat", help="Show recent chat traces with metrics")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--lookback", type=str, default="24h")
    p.set_defaults(func=cmd_chat)

    # errors
    p = sub.add_parser("errors", help="Find traces with errors")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--lookback", type=str, default="24h")
    p.set_defaults(func=cmd_errors)

    # operations
    p = sub.add_parser("operations", help="List all operations")
    p.set_defaults(func=cmd_operations)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
