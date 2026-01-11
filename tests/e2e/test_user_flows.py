"""End-to-end tests for user flows using Playwright."""

import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

# Skip E2E tests if SKIP_E2E_TESTS is set
pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_E2E_TESTS", "false").lower() == "true",
    reason="E2E tests are skipped in this environment",
)


@pytest.fixture(scope="module")
def server():
    """Start the FastAPI server for E2E tests."""
    # Remove any existing database
    db_path = Path("highlight_helper.db")
    if db_path.exists():
        db_path.unlink()

    # Start the server
    server_process = subprocess.Popen(
        ["python", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8765"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for server to start
    time.sleep(3)

    yield "http://127.0.0.1:8765"

    # Stop the server
    server_process.send_signal(signal.SIGTERM)
    server_process.wait(timeout=5)


@pytest.fixture(scope="module")
def browser_context():
    """Create a Playwright browser context."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("Playwright not installed")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 375, "height": 667})
        yield context
        context.close()
        browser.close()


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

        # Navigate to All Highlights
        page.click("text=All Highlights")
        page.wait_for_load_state("networkidle")
        assert "/highlights" in page.url

        # Navigate back to Books
        page.click("header >> text=Books")
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
        page.click("text=Add Highlight")
        page.wait_for_load_state("networkidle")

        assert "add-highlight" in page.url
        assert page.locator("text=Extract from Image").is_visible()
        assert page.locator("text=Enter Manually").is_visible()
        page.close()

    def test_manual_highlight_creation(self, server, browser_context):
        """Test creating a highlight manually."""
        page = browser_context.new_page()

        # Navigate to add highlight page for the test book
        page.goto(server)
        page.wait_for_load_state("networkidle")
        page.click("text=Test Manual Book")
        page.wait_for_load_state("networkidle")
        page.click("text=Add Highlight")
        page.wait_for_load_state("networkidle")

        # Fill in the highlight text
        page.fill('textarea[name="text"]', "This is a test highlight for E2E testing.")
        page.fill('input[name="page_number"]', "42")
        page.fill('textarea[name="note"]', "Added during automated testing")

        # Submit
        page.click('button:has-text("Save Highlight")')
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
    """Tests for responsive/mobile design."""

    @pytest.mark.parametrize(
        "viewport",
        [
            {"width": 320, "height": 568},  # iPhone SE
            {"width": 375, "height": 667},  # iPhone 6/7/8
            {"width": 414, "height": 896},  # iPhone XR
            {"width": 768, "height": 1024},  # iPad
            {"width": 1024, "height": 768},  # Desktop
        ],
    )
    def test_page_renders_at_various_viewports(self, server, viewport):
        """Test that pages render correctly at various viewport sizes."""
        import importlib.util
        import subprocess
        import sys

        if importlib.util.find_spec("playwright") is None:
            pytest.skip("Playwright not installed")

        # Create a small script to run the viewport test
        script = f'''
import sys
from playwright.sync_api import sync_playwright

viewport = {viewport}
server = "{server}"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport=viewport)
    page = context.new_page()

    page.goto(server)
    page.wait_for_load_state("networkidle")

    # Check that the page doesn't have horizontal scrolling
    body_width = page.evaluate("document.body.scrollWidth")
    if body_width > viewport["width"] + 20:
        print(f"FAIL: Page too wide at {{viewport}}")
        sys.exit(1)

    # Check that header is visible
    if not page.locator("header").is_visible():
        print("FAIL: Header not visible")
        sys.exit(1)

    context.close()
    browser.close()
    print("PASS")
    sys.exit(0)
'''
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"Viewport test failed: {result.stderr}"


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

        # Add a highlight
        page.click("text=Add Highlight")
        page.wait_for_load_state("networkidle")
        page.fill('textarea[name="text"]', "Original highlight text")
        page.fill('input[name="page_number"]', "10")
        page.click('button:has-text("Save Highlight")')
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

        # Add a highlight to delete
        page.click("text=Add Highlight")
        page.wait_for_load_state("networkidle")
        page.fill('textarea[name="text"]', "Highlight to be deleted")
        page.fill('input[name="page_number"]', "1")
        page.click('button:has-text("Save Highlight")')
        page.wait_for_load_state("networkidle")

        # Verify highlight exists
        assert page.locator("text=Highlight to be deleted").is_visible()

        # Accept the confirmation dialog
        page.on("dialog", lambda dialog: dialog.accept())

        # Delete the highlight - be more specific with the selector
        delete_buttons = page.locator("button:has-text('Delete'):not(:has-text('Book'))")
        if delete_buttons.count() > 0:
            delete_buttons.first.click()
            page.wait_for_load_state("networkidle")
            # Wait a bit for the page to update
            page.wait_for_timeout(500)

        # Highlight should be gone - check that the specific text is no longer there
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

        # Accept the confirmation dialog
        page.on("dialog", lambda dialog: dialog.accept())

        # Delete the book
        page.click("text=Delete Book")
        page.wait_for_load_state("networkidle")

        # Should redirect to home
        assert page.url.endswith("/") or ":8765" in page.url

        # Book should be gone from home page
        assert not page.locator("text=Book To Delete").is_visible()
        page.close()
