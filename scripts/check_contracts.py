"""Cross-boundary contract checks that unit tests can't see.

Run via `just lint-contracts` (wired into `fc` and `ci`). Each check guards
against a class of bug that has actually shipped:

1. SSE protocol coverage — every chat event type the backend emits must be
   handled by the vendored chatkit bundle. (A stale vendored bundle shipped
   without a TOOL_DONE handler, leaving tool spinners running forever.)
2. Self-contained dependencies — pyproject/uv.lock must not reference path
   dependencies outside the repo. (A ../readwise-sdk path dep broke every
   Docker build with 'Distribution not found'.)
3. Dockerfile COPY sources must exist. (The alembic/ directory was nearly
   missing from the image.)

Exit code 0 = all contracts hold; 1 = violations printed to stderr.
"""

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

errors: list[str] = []


def check_sse_protocol_coverage() -> None:
    """Every event type emitted by the backend must appear in the JS bundle."""
    from chatkit import ChatEventType

    # Discover which events the backend actually emits
    emitted: set[str] = set()
    for py in (REPO / "app").rglob("*.py"):
        src = py.read_text()
        # ChatEvent.init(...) / .text(...) / .error(...) / .done(...) helpers
        for m in re.finditer(r"ChatEvent\.(\w+)\(", src):
            emitted.add(m.group(1).upper())
        # ChatEvent(type=ChatEventType.TOOL_USE, ...)
        for m in re.finditer(r"ChatEventType\.(\w+)", src):
            emitted.add(m.group(1))

    known = {e.name for e in ChatEventType}
    emitted &= known
    if not emitted:
        errors.append("SSE check found no emitted events — check the scan patterns")
        return

    bundle_path = REPO / "static" / "chatkit" / "index.js"
    if not bundle_path.exists():
        errors.append(f"Vendored chatkit bundle missing: {bundle_path}")
        return
    bundle = bundle_path.read_text()

    errors.extend(
        f"Backend emits SSE event '{event.lower()}' but the vendored chatkit "
        f"bundle (static/chatkit/index.js) has no {event} handler — "
        "rebuild ../chatkit and run `just update-chatkit`"
        for event in sorted(emitted)
        if event not in bundle
    )


def check_no_external_path_deps() -> None:
    """pyproject and uv.lock must not point at paths outside the repo."""
    for name in ("pyproject.toml", "uv.lock"):
        text = (REPO / name).read_text()
        errors.extend(
            f"{name} references a path outside the repo: {m.group(1)!r} — "
            "Docker builds cannot see it; vendor a wheel instead "
            "(see readwise_plus-*.whl pattern)"
            for m in re.finditer(r'(?:path|directory)\s*=\s*"(\.\.[^"]*)"', text)
        )


def check_dockerfile_copy_sources() -> None:
    """Every COPY source in the Dockerfile must exist in the build context."""
    dockerfile = REPO / "Dockerfile"
    for line_no, line in enumerate(dockerfile.read_text().splitlines(), 1):
        line = line.strip()
        if not line.startswith("COPY") or "--from=" in line:
            continue
        parts = line.split()[1:]
        sources = parts[:-1]  # last arg is the destination
        errors.extend(
            f"Dockerfile:{line_no} COPY source does not exist: {src!r}"
            for src in sources
            if not (REPO / src.rstrip("/")).exists()
        )


def main() -> int:
    check_sse_protocol_coverage()
    check_no_external_path_deps()
    check_dockerfile_copy_sources()

    if errors:
        print("Contract violations:", file=sys.stderr)
        for e in errors:
            print(f"  ✗ {e}", file=sys.stderr)
        return 1
    print("All contracts hold (SSE protocol coverage, self-contained deps, Dockerfile sources)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
