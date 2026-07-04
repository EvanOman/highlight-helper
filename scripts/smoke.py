"""Post-deploy smoke check — read-only verification of a running instance.

Usage:
    uv run python scripts/smoke.py [base_url]

Default base_url is the local production container behind its root_path:
http://127.0.0.1:18742/highlights

Checks (no writes, no LLM calls):
- Core pages respond: /, /chat, /highlights, /settings
- Settings API returns sane JSON (chat_model + coaching_model present)
- Metrics API responds
- The served chatkit bundle handles every SSE event the backend emits
  (catches stale-vendored-bundle deploys)
- The served CSS is the built artifact, not the CDN
"""

import re
import sys
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
DEFAULT_BASE = "http://127.0.0.1:18742/highlights"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    mark = "✓" if ok else "✗"
    print(f"  {mark} {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def emitted_events() -> set[str]:
    """Event keys the backend emits (same scan as check_contracts)."""
    from chatkit import ChatEventType

    emitted: set[str] = set()
    for py in (REPO / "app").rglob("*.py"):
        src = py.read_text()
        for m in re.finditer(r"ChatEvent\.(\w+)\(", src):
            emitted.add(m.group(1).upper())
        for m in re.finditer(r"ChatEventType\.(\w+)", src):
            emitted.add(m.group(1))
    return emitted & {e.name for e in ChatEventType}


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE).rstrip("/")
    print(f"Smoke-checking {base}")

    client = httpx.Client(timeout=10, follow_redirects=True)

    for path in ("/", "/chat", "/highlights", "/settings"):
        try:
            r = client.get(base + path)
            check(f"GET {path}", r.status_code == 200, f"HTTP {r.status_code}")
        except httpx.HTTPError as e:
            check(f"GET {path}", False, str(e))

    try:
        r = client.get(base + "/api/settings")
        body = r.json() if r.status_code == 200 else {}
        check(
            "GET /api/settings",
            r.status_code == 200 and "chat_model" in body and "coaching_model" in body,
            f"HTTP {r.status_code}, keys: {sorted(body)}",
        )
    except httpx.HTTPError as e:
        check("GET /api/settings", False, str(e))

    try:
        r = client.get(base + "/api/metrics/chat")
        check("GET /api/metrics/chat", r.status_code == 200, f"HTTP {r.status_code}")
    except httpx.HTTPError as e:
        check("GET /api/metrics/chat", False, str(e))

    try:
        r = client.get(base + "/static/chatkit/index.js")
        bundle = r.text if r.status_code == 200 else ""
        missing = sorted(e for e in emitted_events() if e not in bundle)
        check(
            "chatkit bundle handles all emitted SSE events",
            r.status_code == 200 and not missing,
            f"HTTP {r.status_code}, missing handlers: {missing}",
        )
    except httpx.HTTPError as e:
        check("chatkit bundle handles all emitted SSE events", False, str(e))

    try:
        r = client.get(base + "/static/css/app.css")
        check("built CSS served", r.status_code == 200, f"HTTP {r.status_code}")
        home = client.get(base + "/").text
        check("no Tailwind CDN in page", "cdn.tailwindcss.com" not in home)
    except httpx.HTTPError as e:
        check("built CSS served", False, str(e))

    if failures:
        print(f"\nSMOKE FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("\nSMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
