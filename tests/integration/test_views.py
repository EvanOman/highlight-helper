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
        assert "No highlights or notes yet" in response.text

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
        assert "text/html" in response.headers["content-type"]

    async def test_api_not_found_returns_json(self, client: AsyncClient):
        """Test that API 404s return JSON, not HTML."""
        response = await client.get("/api/chat/threads/99999/messages")
        assert response.status_code == 404
        assert "application/json" in response.headers["content-type"]
        assert "detail" in response.json()

    async def test_api_not_found_returns_json_with_root_path(self, client: AsyncClient):
        """Test API 404s return JSON even when request path includes root_path prefix."""
        from httpx import ASGITransport

        from app.main import app

        transport = ASGITransport(app=app, root_path="/highlights")
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/api/chat/threads/99999/messages")
            assert response.status_code == 404
            assert "application/json" in response.headers["content-type"]
            assert "detail" in response.json()

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

    async def test_add_highlight_page_shows_upload_form(self, client: AsyncClient, sample_book):
        """Test add highlight page shows upload form and no editor initially."""
        response = await client.get(f"/books/{sample_book.id}/add-highlight")
        assert response.status_code == 200
        assert "Extract from Image" in response.text
        assert "extract-form" in response.text
        # Editor should NOT be shown initially
        assert "highlight-editor" not in response.text
        assert "__highlightData" not in response.text

    async def test_add_highlight_page_has_manual_section(self, client: AsyncClient, sample_book):
        """Test add highlight page has manual entry section."""
        response = await client.get(f"/books/{sample_book.id}/add-highlight")
        assert response.status_code == 200
        assert "toggleSection" in response.text
        assert "manual-section" in response.text
        assert "manual-chevron" in response.text
        assert "Enter Manually" in response.text

    async def test_add_highlight_page_not_found(self, client: AsyncClient):
        """Test add highlight page for non-existent book."""
        response = await client.get("/books/99999/add-highlight")
        assert response.status_code == 404

    async def test_extract_highlight_form(
        self, client: AsyncClient, sample_book, mock_highlight_extractor_service
    ):
        """Test extracting highlight via form shows highlight editor."""
        fake_image = io.BytesIO(b"fake image data")

        response = await client.post(
            f"/books/{sample_book.id}/extract",
            data={"instructions": "Extract highlighted text"},
            files={"image": ("test.jpg", fake_image, "image/jpeg")},
        )
        assert response.status_code == 200
        # Should show the highlight editor with full text data
        assert "highlight-editor" in response.text
        assert "__highlightData" in response.text
        assert "This is an extracted highlight." in response.text
        assert "Confidence: high" in response.text
        assert "Review" in response.text
        assert "Adjust Selection" in response.text

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


class TestTimelineView:
    """Tests for the timeline feature on book detail page."""

    async def test_book_detail_shows_timeline_with_page_numbers(
        self, client: AsyncClient, sample_book, sample_highlight
    ):
        """Test that timeline is shown when highlights have page numbers."""
        response = await client.get(f"/books/{sample_book.id}")
        assert response.status_code == 200
        # Timeline should be shown (sample_highlight has page_number="42")
        assert "Reading Progress" in response.text
        assert "p. 42" in response.text
        # Check for legend
        assert "Highlights" in response.text
        assert "Notes" in response.text

    async def test_book_detail_hides_timeline_without_page_numbers(
        self, client: AsyncClient, test_session, sample_book
    ):
        """Test that timeline is hidden when no highlights have page numbers."""
        from app.models.highlight import Highlight

        # Create highlight without page number
        highlight = Highlight(
            book_id=sample_book.id,
            text="Highlight without page",
            page_number=None,
        )
        test_session.add(highlight)
        await test_session.commit()

        response = await client.get(f"/books/{sample_book.id}")
        assert response.status_code == 200
        # Timeline should NOT be shown
        assert "Reading Progress" not in response.text

    async def test_book_detail_timeline_shows_correct_page_range(
        self, client: AsyncClient, test_session, sample_book
    ):
        """Test that timeline shows correct min/max page numbers."""
        from app.models.highlight import Highlight

        # Create highlights at different pages
        highlight1 = Highlight(
            book_id=sample_book.id,
            text="First highlight",
            page_number="10",
        )
        highlight2 = Highlight(
            book_id=sample_book.id,
            text="Last highlight",
            page_number="200",
        )
        test_session.add_all([highlight1, highlight2])
        await test_session.commit()

        response = await client.get(f"/books/{sample_book.id}")
        assert response.status_code == 200
        assert "p. 10" in response.text
        assert "p. 200" in response.text

    async def test_book_detail_highlight_cards_have_ids(
        self, client: AsyncClient, sample_book, sample_highlight
    ):
        """Test that highlight cards have IDs for timeline scroll targeting."""
        response = await client.get(f"/books/{sample_book.id}")
        assert response.status_code == 200
        # Check for highlight card ID
        assert f'id="highlight-{sample_highlight.id}"' in response.text

    async def test_book_detail_timeline_single_item_no_duplicate_label(
        self, client: AsyncClient, sample_book, sample_highlight
    ):
        """Test that single item timeline does not show duplicate page labels."""
        response = await client.get(f"/books/{sample_book.id}")
        assert response.status_code == 200
        # Should only show one "p. 42" label, not two
        # Count occurrences of "p. 42" in page labels section
        # The label should appear once (not twice at both ends)
        content = response.text
        # The pattern should not have two adjacent page labels with same value
        assert "p. 42</span>" in content
        # When min == max, we should NOT have a second label
        # The implementation hides the second label when timeline_min_page == timeline_max_page

    async def test_book_detail_timeline_escapes_preview_text(
        self, client: AsyncClient, test_session, sample_book
    ):
        """Test that preview text in tooltip is properly escaped (XSS prevention)."""
        from app.models.highlight import Highlight

        # Create highlight with potentially dangerous content
        highlight = Highlight(
            book_id=sample_book.id,
            text='Test <script>alert("xss")</script> text',
            page_number="50",
        )
        test_session.add(highlight)
        await test_session.commit()

        response = await client.get(f"/books/{sample_book.id}")
        assert response.status_code == 200
        # The script tag should be escaped in the title attribute
        assert "<script>" not in response.text or "&lt;script&gt;" in response.text
        assert (
            'alert("xss")' not in response.text
            or "&#34;" in response.text
            or "&quot;" in response.text
        )


class TestHomePagination:
    """Tests for home page pagination."""

    async def test_home_pagination_controls_hidden_single_page(self, client: AsyncClient):
        """No pagination shown with few books."""
        response = await client.get("/")
        assert response.status_code == 200
        assert 'aria-label="Pagination"' not in response.text

    async def test_home_pagination_shows_controls(self, client: AsyncClient, test_session):
        """Pagination shown when books exceed per_page."""
        from app.models.book import Book

        books = [Book(title=f"Book {i}", author=f"Author {i}") for i in range(30)]
        test_session.add_all(books)
        await test_session.flush()

        response = await client.get("/")
        assert response.status_code == 200
        assert 'aria-label="Pagination"' in response.text
        assert "?page=2" in response.text

    async def test_home_pagination_second_page(self, client: AsyncClient, test_session):
        """Second page shows remaining books."""
        from app.models.book import Book

        books = [Book(title=f"Book {i}", author=f"Author {i}") for i in range(30)]
        test_session.add_all(books)
        await test_session.flush()

        response = await client.get("/?page=2")
        assert response.status_code == 200
        # Should have 6 books on page 2 (30 - 24)

    async def test_home_pagination_invalid_page_clamped(self, client: AsyncClient, test_session):
        """Out-of-range page is clamped to last page."""
        from app.models.book import Book

        books = [Book(title=f"Book {i}", author=f"Author {i}") for i in range(30)]
        test_session.add_all(books)
        await test_session.flush()

        response = await client.get("/?page=999")
        assert response.status_code == 200


class TestHighlightsPagination:
    """Tests for highlights page pagination."""

    async def test_highlights_pagination_controls_hidden(self, client: AsyncClient):
        """No pagination shown with few highlights."""
        response = await client.get("/highlights")
        assert response.status_code == 200
        assert 'aria-label="Pagination"' not in response.text

    async def test_highlights_pagination_shows_controls(self, client: AsyncClient, test_session):
        """Pagination shown when highlights exceed per_page."""
        from app.models.book import Book
        from app.models.highlight import Highlight

        book = Book(title="Paginated Book", author="Author")
        test_session.add(book)
        await test_session.flush()
        await test_session.refresh(book)
        highlights = [Highlight(book_id=book.id, text=f"Highlight {i}") for i in range(25)]
        test_session.add_all(highlights)
        await test_session.flush()

        response = await client.get("/highlights")
        assert response.status_code == 200
        assert 'aria-label="Pagination"' in response.text


class TestBookStarring:
    """Tests for the book starring/pinning feature."""

    async def test_star_book_via_api(self, client: AsyncClient, sample_book):
        """Test starring a book via the API returns correct response."""
        response = await client.post(f"/api/books/{sample_book.id}/star")
        assert response.status_code == 200
        data = response.json()
        assert data == {"starred": True}

    async def test_unstar_book_via_api(self, client: AsyncClient, sample_book):
        """Test toggling star state: star then unstar."""
        # Star the book
        response = await client.post(f"/api/books/{sample_book.id}/star")
        assert response.status_code == 200
        assert response.json()["starred"] is True

        # Unstar the book
        response = await client.post(f"/api/books/{sample_book.id}/star")
        assert response.status_code == 200
        assert response.json()["starred"] is False

    async def test_star_nonexistent_book_returns_404(self, client: AsyncClient):
        """Test starring a non-existent book returns 404."""
        response = await client.post("/api/books/99999/star")
        assert response.status_code == 404

    async def test_starred_books_appear_first_in_home(self, client: AsyncClient, test_session):
        """Test that starred books appear before unstarred books on the home page."""
        from app.models.book import Book

        # Create two books: first created (unstarred) and second created (starred)
        book_old = Book(title="Old Unstarred Book", author="Author A")
        test_session.add(book_old)
        await test_session.flush()

        book_new = Book(title="New Starred Book", author="Author B", is_starred=True)
        test_session.add(book_new)
        await test_session.flush()

        response = await client.get("/")
        assert response.status_code == 200
        content = response.text
        # The starred book should appear before the unstarred one
        starred_pos = content.index("New Starred Book")
        unstarred_pos = content.index("Old Unstarred Book")
        assert starred_pos < unstarred_pos

    async def test_home_page_shows_star_button(self, client: AsyncClient, sample_book):
        """Test that star buttons are rendered on the home page."""
        response = await client.get("/")
        assert response.status_code == 200
        assert "toggleStar" in response.text
        assert "star-btn" in response.text

    async def test_book_detail_shows_star_button(self, client: AsyncClient, sample_book):
        """Test that star button is rendered on the book detail page."""
        response = await client.get(f"/books/{sample_book.id}")
        assert response.status_code == 200
        assert "toggleStarDetail" in response.text
        assert "detail-star-btn" in response.text


class TestBookSearchAPI:
    """Tests for the book search API endpoint."""

    async def test_empty_query_returns_recent_books(self, client: AsyncClient, sample_book):
        """Empty query returns recent books."""
        response = await client.get("/api/chat/books")
        assert response.status_code == 200
        data = response.json()
        assert "books" in data
        assert len(data["books"]) >= 1
        assert data["books"][0]["title"] == sample_book.title

    async def test_empty_q_param_returns_recent_books(self, client: AsyncClient, sample_book):
        """Explicitly empty q= returns recent books."""
        response = await client.get("/api/chat/books?q=")
        assert response.status_code == 200
        data = response.json()
        assert len(data["books"]) >= 1

    async def test_search_by_title(self, client: AsyncClient, sample_book):
        """Query matching title returns correct results."""
        response = await client.get("/api/chat/books?q=Test+Book")
        assert response.status_code == 200
        data = response.json()
        assert len(data["books"]) == 1
        assert data["books"][0]["title"] == "Test Book"
        assert data["books"][0]["id"] == sample_book.id

    async def test_search_by_author(self, client: AsyncClient, sample_book):
        """Query matching author returns correct results."""
        response = await client.get("/api/chat/books?q=Test+Author")
        assert response.status_code == 200
        data = response.json()
        assert len(data["books"]) == 1
        assert data["books"][0]["author"] == "Test Author"

    async def test_search_case_insensitive(self, client: AsyncClient, sample_book):
        """Search is case-insensitive."""
        response = await client.get("/api/chat/books?q=test+book")
        assert response.status_code == 200
        data = response.json()
        assert len(data["books"]) == 1
        assert data["books"][0]["title"] == "Test Book"

    async def test_search_no_match(self, client: AsyncClient, sample_book):
        """Query that does not match any book returns empty list."""
        response = await client.get("/api/chat/books?q=nonexistent+xyz")
        assert response.status_code == 200
        data = response.json()
        assert data["books"] == []

    async def test_results_include_highlight_count(
        self, client: AsyncClient, sample_book, sample_highlight
    ):
        """Results include highlight_count field."""
        response = await client.get("/api/chat/books?q=Test")
        assert response.status_code == 200
        data = response.json()
        assert len(data["books"]) == 1
        assert data["books"][0]["highlight_count"] == 1

    async def test_results_limited_to_ten(self, client: AsyncClient, test_session):
        """Results are limited to 10 books."""
        from app.models.book import Book

        books = [Book(title=f"Search Book {i}", author=f"Author {i}") for i in range(15)]
        test_session.add_all(books)
        await test_session.flush()

        response = await client.get("/api/chat/books?q=Search+Book")
        assert response.status_code == 200
        data = response.json()
        assert len(data["books"]) == 10
