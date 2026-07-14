"""End-to-end tests for user flows using Playwright."""

import contextlib
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import ClassVar

import httpx
import pytest

# Skip E2E tests if SKIP_E2E_TESTS is set
pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_E2E_TESTS", "false").lower() == "true",
    reason="E2E tests are skipped in this environment",
)

E2E_PORT = 8765
E2E_HOST = "127.0.0.1"
E2E_BASE_URL = f"http://{E2E_HOST}:{E2E_PORT}"


def _port_is_free(host: str, port: int) -> bool:
    """Check whether a TCP port has a listener (i.e., something we'd conflict with)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        result = s.connect_ex((host, port))
        # connect_ex returns 0 if it connected (port in use), non-zero if refused
        return result != 0


@pytest.fixture(scope="module")
def server():
    """Start the FastAPI server for E2E tests using an isolated temp database.

    Checks that the target port is free before starting, then polls a
    health-check endpoint instead of using a fixed sleep.
    """
    if not _port_is_free(E2E_HOST, E2E_PORT):
        pytest.fail(
            f"Port {E2E_PORT} is already in use. Free it before running E2E tests "
            "(do NOT kill the occupying process automatically)."
        )

    # Use a temp directory for the database so we never touch the real one
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "e2e_test.db"
        env = {
            **os.environ,
            "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}",
            # Keep retained-upload corpus writes out of the real data/uploads.
            "UPLOADED_IMAGES_DIR": str(Path(tmpdir) / "uploads"),
        }

        # Write stderr to a temp file so we can include it in diagnostics
        # without risking pipe-buffer deadlocks during normal operation.
        stderr_path = Path(tmpdir) / "server_stderr.log"
        stderr_file = open(stderr_path, "w")  # noqa: SIM115

        server_process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                E2E_HOST,
                "--port",
                str(E2E_PORT),
            ],
            stdout=subprocess.DEVNULL,
            stderr=stderr_file,
            env=env,
        )

        # Poll until the server responds (up to 15 s, every 0.2 s)
        deadline = time.monotonic() + 15.0
        server_ready = False
        while time.monotonic() < deadline:
            try:
                resp = httpx.get(f"{E2E_BASE_URL}/", timeout=1.0)
                if resp.status_code < 500:
                    server_ready = True
                    break
            except httpx.ConnectError:
                pass
            except httpx.TimeoutException:
                pass
            time.sleep(0.2)

        if not server_ready:
            # Capture stderr for diagnostics before killing
            server_process.kill()
            server_process.wait(timeout=5)
            stderr_file.close()
            stderr_text = stderr_path.read_text(errors="replace") or "(empty)"
            pytest.fail(
                f"E2E server on {E2E_BASE_URL} did not become ready within 15 s.\n"
                f"Server stderr:\n{stderr_text}"
            )

        yield E2E_BASE_URL

        # Stop the server gracefully with fallback to force kill
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
    """Launch a Playwright browser for the module (internal fixture)."""
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
    """Create a default Playwright browser context (375x667)."""
    context = _playwright_browser.new_context(viewport={"width": 375, "height": 667})
    yield context
    context.close()


class TestHomePageFlow:
    """Tests for home page functionality."""

    def test_home_page_loads(self, server, browser_context):
        """Test that home page loads with empty state."""
        page = browser_context.new_page()
        page.goto(server)
        page.wait_for_load_state("networkidle")

        assert page.title() == "My Books - Highlight Helper"
        assert page.locator("text=No books yet").is_visible()
        page.close()

    def test_navigation_links_work(self, server, browser_context):
        """Test navigation between pages."""
        page = browser_context.new_page()
        page.goto(server)
        page.wait_for_load_state("networkidle")

        # Navigate to Highlights (nav exists at two breakpoints; click the visible one)
        page.locator("nav >> text=Highlights >> visible=true").first.click()
        page.wait_for_load_state("networkidle")
        assert "/highlights" in page.url

        # Navigate back to Books
        page.locator("nav >> text=Books >> visible=true").first.click()
        page.wait_for_load_state("networkidle")
        assert page.url.endswith("/") or page.url.endswith(":8765")

        page.close()


class TestBookManagementFlow:
    """Tests for book management functionality."""

    def test_add_book_page_loads(self, server, browser_context):
        """Test that add book page loads correctly."""
        page = browser_context.new_page()
        page.goto(f"{server}/books/add")
        page.wait_for_load_state("networkidle")

        assert page.title() == "Add Book - Highlight Helper"
        assert page.locator("text=Search for a Book").is_visible()
        assert page.locator("text=Add Manually").is_visible()
        page.close()

    def test_manual_book_creation(self, server, browser_context):
        """Test creating a book manually."""
        page = browser_context.new_page()
        page.goto(f"{server}/books/add")
        page.wait_for_load_state("networkidle")

        # Expand the manual entry section (it's collapsed by default)
        page.click("text=Add Manually")
        page.wait_for_timeout(300)  # Wait for animation

        # Fill in manual form
        page.fill('input[name="title"]', "Test Manual Book")
        page.fill('input[name="author"]', "Test Author")
        page.fill('input[name="isbn"]', "1234567890")

        # Submit
        page.click('button:has-text("Add Book")')
        page.wait_for_load_state("networkidle")

        # Should redirect to book detail page
        assert "/books/" in page.url
        assert page.locator("text=Test Manual Book").is_visible()
        assert page.locator("text=Test Author").is_visible()
        page.close()

    def test_book_appears_on_home_page(self, server, browser_context):
        """Test that created book appears on home page."""
        page = browser_context.new_page()
        page.goto(server)
        page.wait_for_load_state("networkidle")

        # The book from previous test should be visible
        assert page.locator("text=Test Manual Book").is_visible()
        page.close()


class TestHighlightManagementFlow:
    """Tests for highlight management functionality."""

    def test_add_highlight_page_loads(self, server, browser_context):
        """Test that add highlight page loads correctly."""
        page = browser_context.new_page()

        # First, navigate to the book detail page
        page.goto(server)
        page.wait_for_load_state("networkidle")
        page.click("text=Test Manual Book")
        page.wait_for_load_state("networkidle")

        # Click Add Highlight
        page.locator("a:has-text('Add Highlight')").first.click()
        page.wait_for_load_state("networkidle")

        assert "add-highlight" in page.url
        assert page.locator("text=Extract from Image").is_visible()
        assert page.locator("text=Enter Manually").is_visible()
        # No highlight editor should be shown initially
        assert not page.locator("#highlight-editor").is_visible()
        page.close()

    def test_manual_highlight_creation(self, server, browser_context):
        """Test creating a highlight manually via the Enter Manually section."""
        page = browser_context.new_page()

        # Navigate to add highlight page for the test book
        page.goto(server)
        page.wait_for_load_state("networkidle")
        page.click("text=Test Manual Book")
        page.wait_for_load_state("networkidle")
        page.locator("a:has-text('Add Highlight')").first.click()
        page.wait_for_load_state("networkidle")

        # The manual section should be visible (open by default when no extraction)
        # Fill in the highlight text using the manual form fields
        page.fill(
            '#manual-section textarea[name="text"]', "This is a test highlight for E2E testing."
        )
        page.fill('#manual-section input[name="page_number"]', "42")
        page.fill('#manual-section textarea[name="note"]', "Added during automated testing")

        # Submit via the manual section's Save button
        page.click('#manual-section button:has-text("Save Highlight")')
        page.wait_for_load_state("networkidle")

        # Should redirect to book detail with highlight visible
        assert page.locator("text=This is a test highlight").is_visible()
        assert page.locator("text=Page 42").is_visible()
        page.close()

    def test_highlight_appears_in_all_highlights(self, server, browser_context):
        """Test that highlight appears in All Highlights view."""
        page = browser_context.new_page()
        page.goto(f"{server}/highlights")
        page.wait_for_load_state("networkidle")

        assert page.locator("text=This is a test highlight").is_visible()
        assert page.locator("text=Test Manual Book").is_visible()
        page.close()


class TestResponsiveDesign:
    """Tests for responsive/mobile design across multiple viewports.

    Uses the shared module-scoped server and creates browser contexts
    with the desired viewport instead of spawning subprocesses.
    """

    VIEWPORTS: ClassVar[list[tuple[int, int]]] = [
        (320, 568),  # iPhone SE
        (375, 667),  # iPhone 6/7/8
        (768, 1024),  # iPad
        (1280, 800),  # Desktop
    ]

    # Pages to visit at every viewport (relative paths)
    PAGES: ClassVar[list[str]] = [
        "/",  # home
        "/highlights",  # all-highlights
        "/settings",  # settings
        "/chat",  # chat
        # book detail is added dynamically after creating a book
    ]

    # Small allowance for scrollbar/rounding differences across platforms.
    OVERFLOW_TOLERANCE = 5

    @pytest.fixture(scope="class")
    def _book_id(self, server, browser_context):
        """Create a book with a highlight via the UI, return book id."""
        page = browser_context.new_page()
        page.goto(f"{server}/books/add")
        page.wait_for_load_state("networkidle")

        page.click("text=Add Manually")
        page.wait_for_timeout(300)
        page.fill('input[name="title"]', "Responsive Test Book")
        page.fill('input[name="author"]', "Responsive Author")
        page.click('button:has-text("Add Book")')
        page.wait_for_load_state("networkidle")

        # Extract book id from the URL (e.g. /books/5)
        book_id = page.url.rstrip("/").split("/")[-1]

        # Add a highlight so the detail page has content
        page.locator("a:has-text('Add Highlight')").first.click()
        page.wait_for_load_state("networkidle")
        page.fill('#manual-section textarea[name="text"]', "A responsive test highlight.")
        page.fill('#manual-section input[name="page_number"]', "7")
        page.click('#manual-section button:has-text("Save Highlight")')
        page.wait_for_load_state("networkidle")
        page.close()

        return book_id

    @pytest.mark.parametrize("width,height", VIEWPORTS)
    def test_no_horizontal_overflow_and_header_visible(
        self, server, _playwright_browser, width, height, _book_id
    ):
        """At each viewport, visit key pages and assert no overflow + header visible."""
        pages_to_check = [*self.PAGES, f"/books/{_book_id}"]

        context = _playwright_browser.new_context(viewport={"width": width, "height": height})
        page = context.new_page()

        try:
            for path in pages_to_check:
                page.goto(f"{server}{path}")
                page.wait_for_load_state("networkidle")

                scroll_width = page.evaluate("document.documentElement.scrollWidth")
                assert scroll_width <= width + self.OVERFLOW_TOLERANCE, (
                    f"Horizontal overflow on {path} at {width}x{height}: "
                    f"scrollWidth={scroll_width}, viewport={width}"
                )

                assert page.locator("header").is_visible(), (
                    f"Header not visible on {path} at {width}x{height}"
                )
        finally:
            context.close()

    @pytest.mark.parametrize("width,height", [(320, 568), (375, 667)])
    def test_chat_sidebar_toggle_visible_on_mobile(
        self, server, _playwright_browser, width, height
    ):
        """On mobile widths the chat page sidebar toggle button should be visible."""
        context = _playwright_browser.new_context(viewport={"width": width, "height": height})
        page = context.new_page()

        try:
            page.goto(f"{server}/chat")
            page.wait_for_load_state("networkidle")

            toggle = page.locator("#sidebar-toggle")
            assert toggle.is_visible(), (
                f"Sidebar toggle button not visible on chat page at {width}x{height}"
            )
        finally:
            context.close()


class TestEditHighlightFlow:
    """Tests for edit highlight functionality."""

    def test_edit_button_visible_on_book_detail(self, server, browser_context):
        """Test that edit button appears on book detail page."""
        page = browser_context.new_page()

        # First create a book with a highlight
        page.goto(f"{server}/books/add")
        page.wait_for_load_state("networkidle")

        page.click("text=Add Manually")
        page.wait_for_timeout(300)

        page.fill('input[name="title"]', "Edit Test Book")
        page.fill('input[name="author"]', "Edit Test Author")
        page.click('button:has-text("Add Book")')
        page.wait_for_load_state("networkidle")

        # Add a highlight via manual entry
        page.locator("a:has-text('Add Highlight')").first.click()
        page.wait_for_load_state("networkidle")
        page.fill('#manual-section textarea[name="text"]', "Original highlight text")
        page.fill('#manual-section input[name="page_number"]', "10")
        page.click('#manual-section button:has-text("Save Highlight")')
        page.wait_for_load_state("networkidle")

        # Verify edit link is visible
        assert page.locator('a:has-text("Edit")').is_visible()
        page.close()

    def test_edit_highlight_page_loads(self, server, browser_context):
        """Test that edit highlight page loads with current values."""
        page = browser_context.new_page()

        # Navigate to the test book
        page.goto(server)
        page.wait_for_load_state("networkidle")
        page.click("text=Edit Test Book")
        page.wait_for_load_state("networkidle")

        # Click Edit link
        page.click('a:has-text("Edit")')
        page.wait_for_load_state("networkidle")

        # Verify edit page loaded with correct content
        assert "Edit Highlight" in page.title() or "edit" in page.url.lower()
        assert page.locator('textarea[name="text"]').input_value() == "Original highlight text"
        assert page.locator('input[name="page_number"]').input_value() == "10"
        page.close()

    def test_update_highlight_via_edit_form(self, server, browser_context):
        """Test updating a highlight via the edit form."""
        page = browser_context.new_page()

        # Navigate to the test book
        page.goto(server)
        page.wait_for_load_state("networkidle")
        page.click("text=Edit Test Book")
        page.wait_for_load_state("networkidle")

        # Click Edit link
        page.click('a:has-text("Edit")')
        page.wait_for_load_state("networkidle")

        # Update the highlight
        page.fill('textarea[name="text"]', "Updated highlight text via E2E test")
        page.fill('input[name="page_number"]', "99")
        page.fill('textarea[name="note"]', "Updated note")

        # Submit
        page.click('button:has-text("Save Changes")')
        page.wait_for_load_state("networkidle")

        # Should redirect to book detail with updated highlight
        assert "Updated highlight text via E2E test" in page.content()
        assert page.locator("text=Page 99").is_visible()
        page.close()

    def test_edit_button_visible_on_all_highlights(self, server, browser_context):
        """Test that edit button appears on all highlights page."""
        page = browser_context.new_page()
        page.goto(f"{server}/highlights")
        page.wait_for_load_state("networkidle")

        # Verify edit link is visible for the test highlight
        assert page.locator('a:has-text("Edit")').first.is_visible()
        page.close()

    def test_cancel_edit_returns_to_book(self, server, browser_context):
        """Test that cancel button returns to book detail."""
        page = browser_context.new_page()

        # Navigate to the test book
        page.goto(server)
        page.wait_for_load_state("networkidle")
        page.click("text=Edit Test Book")
        page.wait_for_load_state("networkidle")

        # Click Edit link
        page.click('a:has-text("Edit")')
        page.wait_for_load_state("networkidle")

        # Click Cancel
        page.click('a:has-text("Cancel")')
        page.wait_for_load_state("networkidle")

        # Should be back on book detail page
        assert "Edit Test Book" in page.content()
        assert "edit" not in page.url.lower()
        page.close()


class TestDeleteOperations:
    """Tests for delete functionality."""

    def test_delete_highlight(self, server, browser_context):
        """Test deleting a highlight."""
        page = browser_context.new_page()

        # First create a fresh book and highlight for this test
        page.goto(f"{server}/books/add")
        page.wait_for_load_state("networkidle")

        # Expand the manual entry section (it's collapsed by default)
        page.click("text=Add Manually")
        page.wait_for_timeout(300)  # Wait for animation

        page.fill('input[name="title"]', "Delete Test Book")
        page.fill('input[name="author"]', "Delete Test Author")
        page.click('button:has-text("Add Book")')
        page.wait_for_load_state("networkidle")

        # Add a highlight to delete via manual entry
        page.locator("a:has-text('Add Highlight')").first.click()
        page.wait_for_load_state("networkidle")
        page.fill('#manual-section textarea[name="text"]', "Highlight to be deleted")
        page.fill('#manual-section input[name="page_number"]', "1")
        page.click('#manual-section button:has-text("Save Highlight")')
        page.wait_for_load_state("networkidle")

        # Verify highlight exists
        assert page.locator("text=Highlight to be deleted").is_visible()

        # Override window.confirm to always return true (avoids flaky dialog handling)
        page.evaluate("window.confirm = () => true")

        # Find and click the delete button for the highlight
        delete_button = page.locator("form[action*='/highlights/'] button:has-text('Delete')").first
        delete_button.click()
        page.wait_for_load_state("networkidle")

        # Highlight should be gone
        assert not page.locator("text=Highlight to be deleted").is_visible()

        page.close()

    def test_delete_book(self, server, browser_context):
        """Test deleting a book."""
        page = browser_context.new_page()

        # First create a fresh book for this test
        page.goto(f"{server}/books/add")
        page.wait_for_load_state("networkidle")

        # Expand the manual entry section (it's collapsed by default)
        page.click("text=Add Manually")
        page.wait_for_timeout(300)  # Wait for animation

        page.fill('input[name="title"]', "Book To Delete")
        page.fill('input[name="author"]', "Author To Delete")
        page.click('button:has-text("Add Book")')
        page.wait_for_load_state("networkidle")

        # Override window.confirm to always return true (avoids flaky dialog handling)
        page.evaluate("window.confirm = () => true")

        # Click delete and wait for navigation
        page.click("text=Delete Book")
        page.wait_for_load_state("networkidle")

        # Book should be gone from home page
        assert not page.locator("text=Book To Delete").is_visible()
        page.close()
