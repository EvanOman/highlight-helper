"""Integration tests for HTML views."""

import io

from httpx import AsyncClient


class TestHomeView:
    """Tests for the home page."""

    async def test_home_empty(self, client: AsyncClient):
        """Test home page with no books."""
        response = await client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "No books yet" in response.text

    async def test_home_with_books(self, client: AsyncClient, sample_book):
        """Test home page with books."""
        response = await client.get("/")
        assert response.status_code == 200
        assert sample_book.title in response.text
        assert sample_book.author in response.text


class TestAddBookView:
    """Tests for the add book page."""

    async def test_add_book_page(self, client: AsyncClient):
        """Test add book page renders."""
        response = await client.get("/books/add")
        assert response.status_code == 200
        assert "Add a Book" in response.text
        assert "Search for a Book" in response.text

    async def test_add_book_page_has_scan_section(self, client: AsyncClient):
        """Test add book page has collapsible scan section."""
        response = await client.get("/books/add")
        assert response.status_code == 200
        # Check for scan section elements
        assert "scan-section" in response.text
        assert "scan-chevron" in response.text
        assert "Scan Cover or Barcode" in response.text
        assert "scan-spinner" in response.text

    async def test_add_book_page_has_collapsible_sections(self, client: AsyncClient):
        """Test add book page has collapsible sections."""
        response = await client.get("/books/add")
        assert response.status_code == 200
        assert "toggleSection" in response.text
        assert "scan-section" in response.text
        assert "search-section" in response.text
        assert "manual-section" in response.text

    async def test_scan_isbn_form(
        self, client: AsyncClient, mock_isbn_extractor_service, mock_book_lookup_service
    ):
        """Test scanning ISBN from image."""
        from app.services.book_lookup import BookInfo

        mock_book_lookup_service.search_by_isbn.return_value = BookInfo(
            title="Scanned Book",
            author="Scanned Author",
            isbn="9781234567890",
            cover_url="https://example.com/cover.jpg",
            description=None,
        )

        fake_image = io.BytesIO(b"fake image data")

        response = await client.post(
            "/books/scan-isbn",
            files={"image": ("test.jpg", fake_image, "image/jpeg")},
        )
        assert response.status_code == 200
        assert "9781234567890" in response.text
        assert "Scanned Book" in response.text
        assert "Scanned Author" in response.text

    async def test_search_books_page(self, client: AsyncClient, mock_book_lookup_service):
        """Test book search on add book page."""
        from app.services.book_lookup import BookInfo

        mock_book_lookup_service.search_books.return_value = [
            BookInfo(
                title="Search Result",
                author="Result Author",
                isbn="1234567890",
                cover_url=None,
                description=None,
            )
        ]

        response = await client.post(
            "/books/search",
            data={"query": "test query"},
        )
        assert response.status_code == 200
        assert "Search Result" in response.text
        assert "Result Author" in response.text

    async def test_create_book_form(self, client: AsyncClient):
        """Test creating a book via form."""
        response = await client.post(
            "/books/create",
            data={
                "title": "Form Book",
                "author": "Form Author",
                "isbn": "",
                "cover_url": "",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert "/books/" in response.headers["location"]


class TestBookDetailView:
    """Tests for the book detail page."""

    async def test_book_detail_page(self, client: AsyncClient, sample_book):
        """Test book detail page renders."""
        response = await client.get(f"/books/{sample_book.id}")
        assert response.status_code == 200
        assert sample_book.title in response.text
        assert sample_book.author in response.text
        assert "No highlights yet" in response.text

    async def test_book_detail_with_highlights(
        self, client: AsyncClient, sample_book, sample_highlight
    ):
        """Test book detail page with highlights."""
        response = await client.get(f"/books/{sample_book.id}")
        assert response.status_code == 200
        assert sample_highlight.text in response.text

    async def test_book_detail_not_found(self, client: AsyncClient):
        """Test book detail page for non-existent book."""
        response = await client.get("/books/99999")
        assert response.status_code == 404

    async def test_delete_book_form(self, client: AsyncClient, sample_book):
        """Test deleting a book via form."""
        response = await client.post(
            f"/books/{sample_book.id}/delete",
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/"


class TestAddHighlightView:
    """Tests for the add highlight page."""

    async def test_add_highlight_page(self, client: AsyncClient, sample_book):
        """Test add highlight page renders."""
        response = await client.get(f"/books/{sample_book.id}/add-highlight")
        assert response.status_code == 200
        assert "Add Highlight" in response.text
        assert sample_book.title in response.text

    async def test_add_highlight_page_has_loading_animation(self, client: AsyncClient, sample_book):
        """Test add highlight page has loading animation for extraction."""
        response = await client.get(f"/books/{sample_book.id}/add-highlight")
        assert response.status_code == 200
        # Check for loading animation elements
        assert "extract-spinner" in response.text
        assert "Extracting..." in response.text
        assert "animate-spin" in response.text

    async def test_add_highlight_page_has_collapsible_sections(
        self, client: AsyncClient, sample_book
    ):
        """Test add highlight page has collapsible accordion sections."""
        response = await client.get(f"/books/{sample_book.id}/add-highlight")
        assert response.status_code == 200
        # Check for collapsible section elements
        assert "toggleSection" in response.text
        assert "extract-section" in response.text
        assert "extract-chevron" in response.text
        assert "manual-section" in response.text
        assert "manual-chevron" in response.text
        # Check for section headers
        assert "Extract from Image" in response.text
        assert "Enter Manually" in response.text

    async def test_add_highlight_page_not_found(self, client: AsyncClient):
        """Test add highlight page for non-existent book."""
        response = await client.get("/books/99999/add-highlight")
        assert response.status_code == 404

    async def test_extract_highlight_form(
        self, client: AsyncClient, sample_book, mock_highlight_extractor_service
    ):
        """Test extracting highlight via form."""
        fake_image = io.BytesIO(b"fake image data")

        response = await client.post(
            f"/books/{sample_book.id}/extract",
            data={"instructions": "Extract highlighted text"},
            files={"image": ("test.jpg", fake_image, "image/jpeg")},
        )
        assert response.status_code == 200
        assert "This is an extracted highlight." in response.text
        assert "Confidence: high" in response.text

    async def test_create_highlight_form(self, client: AsyncClient, sample_book):
        """Test creating a highlight via form."""
        response = await client.post(
            f"/books/{sample_book.id}/highlights/create",
            data={
                "text": "Form highlight text",
                "note": "",
                "page_number": "",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert f"/books/{sample_book.id}" in response.headers["location"]


class TestAllHighlightsView:
    """Tests for the all highlights page."""

    async def test_all_highlights_empty(self, client: AsyncClient):
        """Test all highlights page with no highlights."""
        response = await client.get("/highlights")
        assert response.status_code == 200
        assert "No highlights yet" in response.text

    async def test_all_highlights_with_data(
        self, client: AsyncClient, sample_book, sample_highlight
    ):
        """Test all highlights page with data."""
        response = await client.get("/highlights")
        assert response.status_code == 200
        assert sample_highlight.text in response.text
        assert sample_book.title in response.text

    async def test_all_highlights_shows_sync_button(
        self, client: AsyncClient, sample_book, sample_highlight
    ):
        """Test that sync button appears for unsynced highlights."""
        response = await client.get("/highlights")
        assert response.status_code == 200
        # Check for sync button (unsynced highlight)
        assert f"sync-btn-{sample_highlight.id}" in response.text
        assert "syncHighlightToReadwise" in response.text


class TestEditHighlightView:
    """Tests for the edit highlight page."""

    async def test_edit_highlight_page(self, client: AsyncClient, sample_book, sample_highlight):
        """Test edit highlight page renders with current values."""
        response = await client.get(
            f"/books/{sample_book.id}/highlights/{sample_highlight.id}/edit"
        )
        assert response.status_code == 200
        assert "Edit Highlight" in response.text
        assert sample_book.title in response.text
        assert sample_highlight.text in response.text

    async def test_edit_highlight_page_shows_sync_info_for_synced(
        self, client: AsyncClient, sample_book, synced_highlight
    ):
        """Test edit page shows sync info for synced highlight."""
        response = await client.get(
            f"/books/{sample_book.id}/highlights/{synced_highlight.id}/edit"
        )
        assert response.status_code == 200
        assert "This highlight is synced to Readwise" in response.text

    async def test_edit_highlight_page_book_not_found(self, client: AsyncClient):
        """Test edit highlight page for non-existent book."""
        response = await client.get("/books/99999/highlights/1/edit")
        assert response.status_code == 404

    async def test_edit_highlight_page_highlight_not_found(self, client: AsyncClient, sample_book):
        """Test edit highlight page for non-existent highlight."""
        response = await client.get(f"/books/{sample_book.id}/highlights/99999/edit")
        assert response.status_code == 404

    async def test_update_highlight_form(self, client: AsyncClient, sample_book, sample_highlight):
        """Test updating a highlight via form."""
        response = await client.post(
            f"/books/{sample_book.id}/highlights/{sample_highlight.id}/update",
            data={
                "text": "Updated text via form",
                "note": "Updated note",
                "page_number": "99",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert f"/books/{sample_book.id}" in response.headers["location"]

        # Verify the update
        detail_response = await client.get(f"/books/{sample_book.id}")
        assert "Updated text via form" in detail_response.text

    async def test_update_highlight_form_clears_optional_fields(
        self, client: AsyncClient, sample_book, sample_highlight
    ):
        """Test updating a highlight can clear optional fields."""
        response = await client.post(
            f"/books/{sample_book.id}/highlights/{sample_highlight.id}/update",
            data={
                "text": "Only text remains",
                "note": "",
                "page_number": "",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

    async def test_update_highlight_form_book_not_found(self, client: AsyncClient):
        """Test update form for non-existent book."""
        response = await client.post(
            "/books/99999/highlights/1/update",
            data={"text": "Updated text"},
            follow_redirects=False,
        )
        assert response.status_code == 404

    async def test_update_highlight_form_highlight_not_found(
        self, client: AsyncClient, sample_book
    ):
        """Test update form for non-existent highlight."""
        response = await client.post(
            f"/books/{sample_book.id}/highlights/99999/update",
            data={"text": "Updated text"},
            follow_redirects=False,
        )
        assert response.status_code == 404


class TestDeleteHighlightView:
    """Tests for highlight deletion."""

    async def test_delete_highlight_form(self, client: AsyncClient, sample_book, sample_highlight):
        """Test deleting a highlight via form."""
        response = await client.post(
            f"/highlights/{sample_highlight.id}/delete",
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert f"/books/{sample_book.id}" in response.headers["location"]
