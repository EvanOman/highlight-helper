"""Full-stack chat self-test with a deterministic fake LLM.

Exercises the seams that unit tests can't see: the SSE protocol between
backend and the vendored chatkit bundle, tool-call round-trips, message
persistence, and metrics recording — all in a real browser against a real
server, with FAKE_LLM=1 so no API calls are made.

Regression coverage:
- Tool cards must flip from running to done when the turn ends (the vendored
  bundle once shipped without a TOOL_DONE handler, and chatkit's handler
  once failed to reach cards inside the shadow root).
- Continuing a thread with persisted tool blocks must not error (the restore
  path once fed Anthropic-format blocks to LiteLLM).
"""

import contextlib
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import expect, sync_playwright

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_E2E_TESTS", "false").lower() == "true",
    reason="E2E tests are skipped in this environment",
)

SELFTEST_PORT = 8766
SELFTEST_HOST = "127.0.0.1"
SELFTEST_BASE_URL = f"http://{SELFTEST_HOST}:{SELFTEST_PORT}"


def _port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((host, port)) != 0


@pytest.fixture(scope="module")
def fake_llm_server():
    """FastAPI server with FAKE_LLM=1 on an isolated temp database."""
    if not _port_is_free(SELFTEST_HOST, SELFTEST_PORT):
        pytest.fail(
            f"Port {SELFTEST_PORT} is already in use. Free it before running "
            "the chat self-test (do NOT kill the occupying process automatically)."
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "selftest.db"
        env = {
            **os.environ,
            "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}",
            "FAKE_LLM": "1",
        }

        stderr_path = Path(tmpdir) / "server_stderr.log"
        stderr_file = open(stderr_path, "w")  # noqa: SIM115

        server_process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                SELFTEST_HOST,
                "--port",
                str(SELFTEST_PORT),
            ],
            stdout=subprocess.DEVNULL,
            stderr=stderr_file,
            env=env,
        )

        deadline = time.monotonic() + 15.0
        ready = False
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{SELFTEST_BASE_URL}/", timeout=1.0).status_code < 500:
                    ready = True
                    break
            except (httpx.ConnectError, httpx.TimeoutException):
                pass
            time.sleep(0.2)

        if not ready:
            server_process.kill()
            server_process.wait(timeout=5)
            stderr_file.close()
            pytest.fail(
                f"Self-test server did not become ready within 15 s.\n"
                f"Server stderr:\n{stderr_path.read_text(errors='replace') or '(empty)'}"
            )

        yield SELFTEST_BASE_URL

        try:
            server_process.send_signal(signal.SIGTERM)
            server_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_process.kill()
            server_process.wait(timeout=5)
        finally:
            with contextlib.suppress(Exception):
                stderr_file.close()


@pytest.fixture(scope="module")
def page_ctx(fake_llm_server):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        yield context
        context.close()
        browser.close()


class TestChatSelfTest:
    """Drive a full chat turn through the real stack with the fake LLM."""

    def test_tool_call_turn_completes_cleanly(self, fake_llm_server, page_ctx):
        page = page_ctx.new_page()
        page.goto(f"{fake_llm_server}/chat")
        page.wait_for_load_state("networkidle")

        # Send a message (fake LLM always does one tool round then answers)
        chat_input = page.locator("ck-input textarea, ck-input input").first
        chat_input.fill("self-test message")
        chat_input.press("Enter")

        # The fake answer must stream in (Playwright selectors pierce shadow DOM)
        expect(page.locator("ck-message", has_text="deterministic fake answer")).to_be_visible(
            timeout=15000
        )

        # The tool card must exist and flip to done — never remain running
        tool_card = page.locator("ck-tool-card")
        expect(tool_card).to_have_count(1, timeout=5000)
        expect(tool_card).to_have_attribute("status", "done", timeout=5000)

        # No error message rendered
        assert page.locator("ck-message[role='error']").count() == 0

        # Metrics were recorded for the turn
        metrics = httpx.get(f"{fake_llm_server}/api/metrics/chat", timeout=5).json()
        assert metrics["summary"]["total_requests"] >= 1

        page.close()

    def test_continuing_tool_thread_does_not_error(self, fake_llm_server, page_ctx):
        """Second message on a thread with persisted tool blocks must work.

        This is the exact production failure: restoring Anthropic-format
        tool blocks into an OpenAI conversation.
        """
        page = page_ctx.new_page()
        page.goto(f"{fake_llm_server}/chat")
        page.wait_for_load_state("networkidle")

        chat_input = page.locator("ck-input textarea, ck-input input").first
        chat_input.fill("first message")
        chat_input.press("Enter")
        expect(page.locator("ck-message", has_text="deterministic fake answer")).to_be_visible(
            timeout=15000
        )

        # Follow-up on the same thread — history now contains tool blocks
        chat_input.fill("follow-up message")
        chat_input.press("Enter")

        expect(
            page.locator("ck-message", has_text="deterministic fake answer").nth(1)
        ).to_be_visible(timeout=15000)
        assert page.locator("ck-message[role='error']").count() == 0

        # Both tool cards resolved
        for i in range(page.locator("ck-tool-card").count()):
            expect(page.locator("ck-tool-card").nth(i)).to_have_attribute(
                "status", "done", timeout=5000
            )

        page.close()
