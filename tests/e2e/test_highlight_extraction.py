"""E2E tests for the honest add-highlight extraction flow.

Runs the real server with FAKE_LLM=1 so the vision extractor is a
deterministic fake (see app/services/llm_fake.py). Behavior is keyed off
the instructions text:
  - "FAKE_EMPTY"   -> empty extraction (silent-failure regression coverage)
  - "FAKE_NOMATCH" -> not_found match (failed-match flow, no pre-selection)
  - anything else  -> exact match spanning a hyphenated line break, so a
                      save round-trip proves offset-sliced text fidelity.
"""

import contextlib
import io
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

from app.services.llm_fake import FAKE_HIGHLIGHT_SAVED

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_E2E_TESTS", "false").lower() == "true",
    reason="E2E tests are skipped in this environment",
)

EXTRACT_PORT = 8767
EXTRACT_HOST = "127.0.0.1"
EXTRACT_BASE_URL = f"http://{EXTRACT_HOST}:{EXTRACT_PORT}"


def _port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((host, port)) != 0


def _make_jpeg(width: int = 320, height: int = 240) -> bytes:
    """Generate a small valid JPEG in memory (content is irrelevant to the fake)."""
    from PIL import Image

    img = Image.new("RGB", (width, height), color=(240, 230, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue()


@pytest.fixture(scope="module")
def fake_llm_server():
    """FastAPI server with FAKE_LLM=1 on an isolated temp database."""
    if not _port_is_free(EXTRACT_HOST, EXTRACT_PORT):
        pytest.fail(
            f"Port {EXTRACT_PORT} is already in use. Free it before running "
            "the extraction E2E tests (do NOT kill the occupying process automatically)."
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "extract_e2e.db"
        env = {
            **os.environ,
            "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}",
            "FAKE_LLM": "1",
            # Keep retained-upload corpus writes out of the real data/uploads.
            "UPLOADED_IMAGES_DIR": str(Path(tmpdir) / "uploads"),
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
                EXTRACT_HOST,
                "--port",
                str(EXTRACT_PORT),
            ],
            stdout=subprocess.DEVNULL,
            stderr=stderr_file,
            env=env,
        )

        deadline = time.monotonic() + 15.0
        ready = False
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{EXTRACT_BASE_URL}/", timeout=1.0).status_code < 500:
                    ready = True
                    break
            except (httpx.ConnectError, httpx.TimeoutException):
                pass
            time.sleep(0.2)

        if not ready:
            server_process.kill()
            server_process.wait(timeout=5)
            stderr_file.close()
            stderr_text = stderr_path.read_text(errors="replace") or "(empty)"
            pytest.fail(
                f"E2E server on {EXTRACT_BASE_URL} did not become ready within 15 s.\n"
                f"Server stderr:\n{stderr_text}"
            )

        yield EXTRACT_BASE_URL

        try:
            server_process.send_signal(signal.SIGTERM)
            server_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_process.kill()
            server_process.wait(timeout=2)
        except Exception:
            with contextlib.suppress(Exception):
                server_process.kill()
        finally:
            stderr_file.close()


@pytest.fixture(scope="module")
def _playwright_browser():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("Playwright not installed")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture(scope="module")
def browser_context(_playwright_browser):
    context = _playwright_browser.new_context(viewport={"width": 375, "height": 667})
    yield context
    context.close()


@pytest.fixture(scope="module")
def jpeg_path(tmp_path_factory) -> Path:
    """A small JPEG on disk for Playwright file uploads."""
    path = tmp_path_factory.mktemp("images") / "page.jpg"
    path.write_bytes(_make_jpeg())
    return path


@pytest.fixture(scope="module")
def large_jpeg_path(tmp_path_factory) -> Path:
    """A >2000px JPEG to exercise the client-side downscale path."""
    path = tmp_path_factory.mktemp("images") / "big_page.jpg"
    path.write_bytes(_make_jpeg(2600, 1950))
    return path


def _create_book(page, server: str, title: str) -> None:
    page.goto(f"{server}/books/add")
    page.wait_for_load_state("networkidle")
    page.click("text=Add Manually")
    page.wait_for_timeout(300)
    page.fill('input[name="title"]', title)
    page.fill('input[name="author"]', "E2E Author")
    page.click('button:has-text("Add Book")')
    page.wait_for_load_state("networkidle")


def _open_add_highlight(page) -> None:
    page.locator("a:has-text('Add Highlight')").first.click()
    page.wait_for_load_state("networkidle")


def _extract(page, image_path: Path, instructions: str) -> None:
    page.set_input_files('input[name="image"]', str(image_path))
    page.fill('textarea[name="instructions"]', instructions)
    page.click("#extract-btn")


class TestExtractionHonesty:
    def test_empty_extraction_shows_explicit_error(
        self, fake_llm_server, browser_context, jpeg_path
    ):
        """Extraction failure renders an error state, never a silent form."""
        page = browser_context.new_page()
        _create_book(page, fake_llm_server, "Empty Extraction Book")
        _open_add_highlight(page)

        _extract(page, jpeg_path, "FAKE_EMPTY please")
        page.wait_for_selector("#extract-error")

        assert "read the page" in page.locator("#extract-error").inner_text()
        # Instructions preserved for the retry
        assert page.locator('textarea[name="instructions"]').first.input_value() == (
            "FAKE_EMPTY please"
        )
        # Manual entry accordion is open as the fallback path
        assert page.locator("#manual-section").is_visible()
        # No editor rendered
        assert page.locator("#highlight-editor").count() == 0
        page.close()

    def test_failed_match_requires_manual_selection(
        self, fake_llm_server, browser_context, jpeg_path
    ):
        """Whole-page fallback shows the notice, no pre-selection, gated Save."""
        page = browser_context.new_page()
        _create_book(page, fake_llm_server, "Failed Match Book")
        _open_add_highlight(page)

        _extract(page, jpeg_path, "FAKE_NOMATCH the marked passage")
        page.wait_for_selector("#match-failed-notice")

        assert "couldn't locate the highlighted passage" in (
            page.locator("#match-failed-notice").inner_text()
        )
        # No green badge on a failed match — no badge at all
        assert page.locator("#confidence-badge").count() == 0
        # Nothing pre-selected; Save disabled; hidden input empty
        assert page.locator(".highlight-word.highlighted").count() == 0
        assert page.locator("#save-highlight-btn").is_disabled()
        assert page.locator("#highlight-text-input").input_value() == ""

        # Tap first and last word of the passage to select it manually
        page.locator(".highlight-word").nth(1).click()  # "quick"
        page.locator(".highlight-word").nth(8).click()  # "dog."
        assert page.locator(".highlight-word.highlighted").count() == 8
        assert page.locator("#save-highlight-btn").is_enabled()
        assert (
            page.locator("#highlight-text-input").input_value()
            == "quick brown fox jumps over the lazy dog."
        )

        # Save and verify the manually selected text round-trips exactly
        page.click("#save-highlight-btn")
        page.wait_for_load_state("networkidle")
        assert page.locator("text=quick brown fox jumps over the lazy dog.").is_visible()
        page.close()

    def test_successful_extraction_save_preserves_offset_sliced_text(
        self, fake_llm_server, browser_context, large_jpeg_path
    ):
        """Saving keeps the exact char-offset slice: hyphenated line break
        rejoined, newlines collapsed — never a word-join reflow.

        Uses a >2000px photo so the client-side canvas downscale path runs
        before upload.
        """
        page = browser_context.new_page()
        _create_book(page, fake_llm_server, "Fidelity Book")
        _open_add_highlight(page)

        _extract(page, large_jpeg_path, "the highlighted text")
        page.wait_for_selector("#highlight-editor")

        # Exact match: green badge allowed, some words pre-highlighted
        assert page.locator("#confidence-badge").inner_text().strip() == "Confidence: high"
        assert page.locator(".highlight-word.highlighted").count() > 0
        # The hidden input holds the cleaned offset slice, not a word join
        assert page.locator("#highlight-text-input").input_value() == FAKE_HIGHLIGHT_SAVED

        page.click("#save-highlight-btn")
        page.wait_for_load_state("networkidle")
        assert page.locator(f"text={FAKE_HIGHLIGHT_SAVED}").is_visible()
        page.close()

    def test_re_extract_without_reupload(self, fake_llm_server, browser_context, jpeg_path):
        """Re-extract re-runs extraction with edited instructions, no new upload."""
        page = browser_context.new_page()
        _create_book(page, fake_llm_server, "Re-extract Book")
        _open_add_highlight(page)

        _extract(page, jpeg_path, "the highlighted text")
        page.wait_for_selector("#highlight-editor")
        assert page.locator("#re-extract-form").is_visible()

        # Re-extract with instructions that trigger the failed-match fake
        page.fill("#re-extract-instructions", "FAKE_NOMATCH try the underlined part")
        page.click("#re-extract-btn")
        page.wait_for_selector("#match-failed-notice")
        assert page.locator("#save-highlight-btn").is_disabled()

        # And back: re-extract again into a clean exact match
        page.fill("#re-extract-instructions", "the highlighted text")
        page.click("#re-extract-btn")
        page.wait_for_selector("#confidence-badge")
        assert page.locator("#match-failed-notice").count() == 0
        assert page.locator("#highlight-text-input").input_value() == FAKE_HIGHLIGHT_SAVED
        page.close()
