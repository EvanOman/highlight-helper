"""Unit tests for services."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.book_lookup import BookLookupService
from app.services.highlight_extractor import (
    ExtractedHighlight,
    HighlightExtractorService,
)
from app.services.isbn_extractor import (
    ExtractedISBN,
    ISBNExtractorService,
)
from app.services.readwise import (
    ReadwiseService,
    ReadwiseSyncResult,
    sync_highlight_background,
)


class TestBookLookupService:
    """Tests for the BookLookupService."""

    async def test_search_books_success(self):
        """Test successful book search."""
        service = BookLookupService()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "totalItems": 1,
            "items": [
                {
                    "volumeInfo": {
                        "title": "Test Book",
                        "authors": ["Test Author"],
                        "industryIdentifiers": [{"type": "ISBN_13", "identifier": "9781234567890"}],
                        "imageLinks": {"thumbnail": "http://example.com/cover.jpg"},
                        "description": "A test book description.",
                    }
                }
            ],
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(service, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            results = await service.search_books("test query")

        assert len(results) == 1
        assert results[0].title == "Test Book"
        assert results[0].author == "Test Author"
        assert results[0].isbn == "9781234567890"
        assert results[0].cover_url == "https://example.com/cover.jpg"

    async def test_search_books_no_results(self):
        """Test book search with no results."""
        service = BookLookupService()

        mock_response = MagicMock()
        mock_response.json.return_value = {"totalItems": 0, "items": []}
        mock_response.raise_for_status = MagicMock()

        with patch.object(service, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            results = await service.search_books("nonexistent book xyz")

        assert len(results) == 0

    async def test_search_books_multiple_authors(self):
        """Test book search with multiple authors."""
        service = BookLookupService()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "totalItems": 1,
            "items": [
                {
                    "volumeInfo": {
                        "title": "Collaborative Book",
                        "authors": ["Author One", "Author Two", "Author Three"],
                    }
                }
            ],
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(service, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            results = await service.search_books("collaborative")

        assert results[0].author == "Author One, Author Two, Author Three"

    async def test_search_by_isbn_found(self):
        """Test ISBN search when book is found."""
        service = BookLookupService()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "totalItems": 1,
            "items": [
                {
                    "volumeInfo": {
                        "title": "ISBN Book",
                        "authors": ["ISBN Author"],
                    }
                }
            ],
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(service, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await service.search_by_isbn("9781234567890")

        assert result is not None
        assert result.title == "ISBN Book"
        assert result.isbn == "9781234567890"

    async def test_search_by_isbn_not_found(self):
        """Test ISBN search when book is not found."""
        service = BookLookupService()

        mock_response = MagicMock()
        mock_response.json.return_value = {"totalItems": 0}
        mock_response.raise_for_status = MagicMock()

        with patch.object(service, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await service.search_by_isbn("0000000000")

        assert result is None


class TestHighlightExtractorService:
    """Tests for the HighlightExtractorService."""

    def test_service_initialization_with_mock_lm(self):
        """Test that service can be initialized with a mock LM."""
        mock_lm = MagicMock()
        service = HighlightExtractorService(lm=mock_lm)
        assert service._lm == mock_lm
        assert service._extractor is not None

    async def test_extract_highlight_success(self):
        """Test successful highlight extraction."""
        mock_lm = MagicMock()
        service = HighlightExtractorService(lm=mock_lm)

        # Mock the extractor module
        mock_result = ExtractedHighlight(
            full_text="Page text before. Extracted text. Page text after.",
            highlight_text="Extracted text",
            confidence="high",
            page_number="42",
            highlight_start=18,
            highlight_end=32,
        )

        # Create an async function that returns our mock result
        async def mock_async_extract(*args, **kwargs):
            return mock_result

        with patch("app.services.highlight_extractor.dspy.Image"):
            with patch(
                "app.services.highlight_extractor.dspy.asyncify",
                return_value=mock_async_extract,
            ):
                with patch("app.services.highlight_extractor.dspy.context"):
                    result = await service.extract_highlight(
                        image_bytes=b"fake image data",
                        filename="test.jpg",
                        instructions="Extract the highlighted text",
                    )

        assert result.highlight_text == "Extracted text"
        assert result.full_text == "Page text before. Extracted text. Page text after."
        assert result.confidence == "high"
        assert result.page_number == "42"
        assert result.highlight_start == 18
        assert result.highlight_end == 32

    async def test_extract_highlight_error_fallback(self):
        """Test that errors during extraction return fallback response."""
        mock_lm = MagicMock()
        service = HighlightExtractorService(lm=mock_lm)

        # Make asyncify raise an exception
        with patch("app.services.highlight_extractor.dspy.Image"):
            with patch(
                "app.services.highlight_extractor.dspy.asyncify",
                side_effect=Exception("API Error"),
            ):
                with patch("app.services.highlight_extractor.dspy.context"):
                    result = await service.extract_highlight(
                        image_bytes=b"fake image data",
                        filename="test.jpg",
                        instructions="Extract the highlighted text",
                    )

        assert result.highlight_text == ""
        assert result.full_text == ""
        assert result.confidence == "low"
        assert result.page_number is None

    async def test_extract_highlight_image_parsing_error_fallback(self):
        """Test that dspy.Image parsing errors return fallback response.

        This test verifies the fix for the bug where dspy.Image() was called
        outside the try/except block, causing unhandled exceptions when
        image parsing failed.
        """
        mock_lm = MagicMock()
        service = HighlightExtractorService(lm=mock_lm)

        # Make dspy.Image raise an exception (simulates invalid image data)
        with patch(
            "app.services.highlight_extractor.dspy.Image",
            side_effect=Exception("Invalid image data"),
        ):
            result = await service.extract_highlight(
                image_bytes=b"invalid image data",
                filename="test.jpg",
                instructions="Extract the highlighted text",
            )

        # Should return fallback response, not raise an exception
        assert result.highlight_text == ""
        assert result.full_text == ""
        assert result.confidence == "low"
        assert result.page_number is None

    def test_extracted_highlight_model(self):
        """Test ExtractedHighlight Pydantic model."""
        # Test with all fields
        highlight = ExtractedHighlight(
            full_text="Full page text. Some text. More text.",
            highlight_text="Some text",
            confidence="high",
            page_number="123",
            highlight_start=16,
            highlight_end=25,
        )
        assert highlight.full_text == "Full page text. Some text. More text."
        assert highlight.highlight_text == "Some text"
        assert highlight.confidence == "high"
        assert highlight.page_number == "123"
        assert highlight.highlight_start == 16
        assert highlight.highlight_end == 25

        # Test with defaults
        highlight_default = ExtractedHighlight()
        assert highlight_default.full_text == ""
        assert highlight_default.highlight_text == ""
        assert highlight_default.confidence == "low"
        assert highlight_default.page_number is None
        assert highlight_default.highlight_start == 0
        assert highlight_default.highlight_end == 0

    def test_extracted_highlight_model_serialization(self):
        """Test ExtractedHighlight JSON serialization."""
        highlight = ExtractedHighlight(
            full_text="Full text here",
            highlight_text="Test text",
            confidence="medium",
            page_number="42",
            highlight_start=0,
            highlight_end=9,
        )
        data = highlight.model_dump()
        assert data == {
            "full_text": "Full text here",
            "highlight_text": "Test text",
            "confidence": "medium",
            "page_number": "42",
            "highlight_start": 0,
            "highlight_end": 9,
            "usage": None,
        }

    async def test_extract_highlight_with_instruction_based_request(self):
        """Test extraction with instruction-based request (not visual highlights)."""
        mock_lm = MagicMock()
        service = HighlightExtractorService(lm=mock_lm)

        mock_result = ExtractedHighlight(
            full_text="Some other text. The sentence about love from the book. Even more text.",
            highlight_text="The sentence about love from the book",
            confidence="high",
            page_number="123",
            highlight_start=17,
            highlight_end=54,
        )

        async def mock_async_extract(*args, **kwargs):
            return mock_result

        with patch("app.services.highlight_extractor.dspy.Image"):
            with patch(
                "app.services.highlight_extractor.dspy.asyncify",
                return_value=mock_async_extract,
            ):
                with patch("app.services.highlight_extractor.dspy.context"):
                    result = await service.extract_highlight(
                        image_bytes=b"fake image data",
                        filename="test.jpg",
                        instructions="grab the sentence about love",
                    )

        assert result.highlight_text == "The sentence about love from the book"
        assert (
            result.full_text
            == "Some other text. The sentence about love from the book. Even more text."
        )
        assert result.confidence == "high"
        assert result.page_number == "123"


class TestISBNExtractorService:
    """Tests for the ISBNExtractorService."""

    def test_service_initialization_with_mock_lm(self):
        """Test that service can be initialized with a mock LM."""
        mock_lm = MagicMock()
        service = ISBNExtractorService(lm=mock_lm)
        assert service._lm == mock_lm
        assert service._extractor is not None

    async def test_extract_isbn_success(self):
        """Test successful ISBN extraction."""
        mock_lm = MagicMock()
        service = ISBNExtractorService(lm=mock_lm)

        mock_result = ExtractedISBN(
            isbn="9781234567890",
            confidence="high",
            source="barcode",
        )

        async def mock_async_extract(*args, **kwargs):
            return mock_result

        with patch("app.services.isbn_extractor.dspy.Image"):
            with patch(
                "app.services.isbn_extractor.dspy.asyncify",
                return_value=mock_async_extract,
            ):
                with patch("app.services.isbn_extractor.dspy.context"):
                    result = await service.extract_isbn(
                        image_bytes=b"fake image data",
                        filename="test.jpg",
                    )

        assert result.isbn == "9781234567890"
        assert result.confidence == "high"
        assert result.source == "barcode"

    async def test_extract_isbn_cleans_non_digits(self):
        """Test that extracted ISBN is cleaned of non-digit characters."""
        mock_lm = MagicMock()
        service = ISBNExtractorService(lm=mock_lm)

        # ISBN with hyphens should be cleaned
        mock_result = ExtractedISBN(
            isbn="978-1-234-56789-0",
            confidence="high",
            source="text",
        )

        async def mock_async_extract(*args, **kwargs):
            return mock_result

        with patch("app.services.isbn_extractor.dspy.Image"):
            with patch(
                "app.services.isbn_extractor.dspy.asyncify",
                return_value=mock_async_extract,
            ):
                with patch("app.services.isbn_extractor.dspy.context"):
                    result = await service.extract_isbn(
                        image_bytes=b"fake image data",
                        filename="test.jpg",
                    )

        assert result.isbn == "9781234567890"

    async def test_extract_isbn_error_fallback(self):
        """Test that errors during extraction return fallback response."""
        mock_lm = MagicMock()
        service = ISBNExtractorService(lm=mock_lm)

        with patch("app.services.isbn_extractor.dspy.Image"):
            with patch(
                "app.services.isbn_extractor.dspy.asyncify",
                side_effect=Exception("API Error"),
            ):
                with patch("app.services.isbn_extractor.dspy.context"):
                    result = await service.extract_isbn(
                        image_bytes=b"fake image data",
                        filename="test.jpg",
                    )

        assert result.isbn == ""
        assert result.confidence == "low"
        assert result.source == "unknown"

    async def test_extract_isbn_image_parsing_error_fallback(self):
        """Test that dspy.Image parsing errors return fallback response.

        This test verifies the fix for the bug where dspy.Image() was called
        outside the try/except block, causing unhandled exceptions when
        image parsing failed. This is the same bug that was fixed in
        highlight_extractor.py.
        """
        mock_lm = MagicMock()
        service = ISBNExtractorService(lm=mock_lm)

        # Make dspy.Image raise an exception (simulates invalid image data)
        with patch(
            "app.services.isbn_extractor.dspy.Image",
            side_effect=Exception("Invalid image data"),
        ):
            result = await service.extract_isbn(
                image_bytes=b"invalid image data",
                filename="test.jpg",
            )

        # Should return fallback response, not raise an exception
        assert result.isbn == ""
        assert result.confidence == "low"
        assert result.source == "unknown"

    def test_extracted_isbn_model(self):
        """Test ExtractedISBN Pydantic model."""
        # Test with all fields
        isbn = ExtractedISBN(
            isbn="9781234567890",
            confidence="high",
            source="barcode",
        )
        assert isbn.isbn == "9781234567890"
        assert isbn.confidence == "high"
        assert isbn.source == "barcode"

        # Test with defaults
        isbn_default = ExtractedISBN()
        assert isbn_default.isbn == ""
        assert isbn_default.confidence == "low"
        assert isbn_default.source == "unknown"


class TestReadwiseService:
    """Tests for the ReadwiseService using the readwise-plus SDK."""

    def test_is_configured_without_token(self):
        """Test is_configured returns False without token."""
        mock_settings = MagicMock()
        mock_settings.readwise_api_token = None
        with patch("app.services.readwise.get_settings", return_value=mock_settings):
            service = ReadwiseService(api_token=None)
            assert service.is_configured is False

    def test_is_configured_with_token(self):
        """Test is_configured returns True with token."""
        service = ReadwiseService(api_token="test_token")
        assert service.is_configured is True

    async def test_validate_token_success(self):
        """Test successful token validation."""
        service = ReadwiseService(api_token="valid_token")

        mock_client = AsyncMock()
        mock_client.validate_token = AsyncMock(return_value=True)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("app.services.readwise.AsyncReadwiseClient", return_value=mock_client):
            result = await service.validate_token()

        assert result is True

    async def test_validate_token_invalid(self):
        """Test token validation with invalid token."""
        service = ReadwiseService(api_token="invalid_token")

        mock_client = AsyncMock()
        mock_client.validate_token = AsyncMock(return_value=False)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("app.services.readwise.AsyncReadwiseClient", return_value=mock_client):
            result = await service.validate_token()

        assert result is False

    async def test_validate_token_no_token(self):
        """Test token validation without token configured."""
        mock_settings = MagicMock()
        mock_settings.readwise_api_token = None
        with patch("app.services.readwise.get_settings", return_value=mock_settings):
            service = ReadwiseService(api_token=None)
            result = await service.validate_token()
            assert result is False

    async def test_send_highlight_success(self):
        """Test successful highlight send."""
        service = ReadwiseService(api_token="test_token")

        # Mock PushResult from the SDK
        mock_push_result = MagicMock()
        mock_push_result.success = True
        mock_push_result.highlight_id = 67890

        mock_pusher = MagicMock()
        mock_pusher.push = AsyncMock(return_value=mock_push_result)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("app.services.readwise.AsyncReadwiseClient", return_value=mock_client),
            patch("app.services.readwise.AsyncHighlightPusher", return_value=mock_pusher),
        ):
            result = await service.send_highlight(
                text="Test highlight text",
                title="Test Book",
                author="Test Author",
                note="My note",
                page_number="42",
                highlighted_at=datetime(2024, 1, 1, tzinfo=UTC),
            )

        assert result.success is True
        assert result.readwise_id == "67890"
        assert result.error is None

    async def test_send_highlight_no_token(self):
        """Test send_highlight without token configured."""
        mock_settings = MagicMock()
        mock_settings.readwise_api_token = None
        with patch("app.services.readwise.get_settings", return_value=mock_settings):
            service = ReadwiseService(api_token=None)

            result = await service.send_highlight(
                text="Test highlight",
                title="Test Book",
                author="Test Author",
            )

            assert result.success is False
            assert "not configured" in result.error

    async def test_send_highlight_api_error(self):
        """Test send_highlight with API error."""
        service = ReadwiseService(api_token="test_token")

        # Mock a failed PushResult
        mock_push_result = MagicMock()
        mock_push_result.success = False
        mock_push_result.error = "API error: 500 Internal Server Error"

        mock_pusher = MagicMock()
        mock_pusher.push = AsyncMock(return_value=mock_push_result)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("app.services.readwise.AsyncReadwiseClient", return_value=mock_client),
            patch("app.services.readwise.AsyncHighlightPusher", return_value=mock_pusher),
        ):
            result = await service.send_highlight(
                text="Test highlight",
                title="Test Book",
                author="Test Author",
            )

        assert result.success is False
        assert "API error" in result.error

    async def test_send_highlight_network_error(self):
        """Test send_highlight with network error."""
        service = ReadwiseService(api_token="test_token")

        mock_pusher = MagicMock()
        mock_pusher.push = AsyncMock(side_effect=Exception("Connection failed"))

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("app.services.readwise.AsyncReadwiseClient", return_value=mock_client),
            patch("app.services.readwise.AsyncHighlightPusher", return_value=mock_pusher),
        ):
            result = await service.send_highlight(
                text="Test highlight",
                title="Test Book",
                author="Test Author",
            )

        assert result.success is False
        assert "Error syncing" in result.error

    async def test_send_highlights_batch_success(self):
        """Test successful batch highlight send."""
        service = ReadwiseService(api_token="test_token")

        # Mock batch results
        mock_result_1 = MagicMock()
        mock_result_1.success = True
        mock_result_1.highlight_id = 111

        mock_result_2 = MagicMock()
        mock_result_2.success = True
        mock_result_2.highlight_id = 222

        mock_pusher = MagicMock()
        mock_pusher.push_batch = AsyncMock(return_value=[mock_result_1, mock_result_2])

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("app.services.readwise.AsyncReadwiseClient", return_value=mock_client),
            patch("app.services.readwise.AsyncHighlightPusher", return_value=mock_pusher),
        ):
            result = await service.send_highlights(
                [
                    {
                        "text": "Highlight 1",
                        "title": "Test Book",
                        "author": "Test Author",
                    },
                    {
                        "text": "Highlight 2",
                        "title": "Test Book",
                        "author": "Test Author",
                    },
                ]
            )

        assert result.total == 2
        assert result.synced == 2
        assert result.failed == 0
        assert len(result.results) == 2

    async def test_send_highlights_empty_list(self):
        """Test send_highlights with empty list."""
        service = ReadwiseService(api_token="test_token")

        result = await service.send_highlights([])

        assert result.total == 0
        assert result.synced == 0
        assert result.failed == 0

    async def test_send_highlights_no_token(self):
        """Test send_highlights without token configured."""
        mock_settings = MagicMock()
        mock_settings.readwise_api_token = None
        with patch("app.services.readwise.get_settings", return_value=mock_settings):
            service = ReadwiseService(api_token=None)

            result = await service.send_highlights(
                [{"text": "Test", "title": "Book", "author": "Author"}]
            )

            assert result.total == 1
            assert result.synced == 0
            assert result.failed == 1

    async def test_update_highlight_success(self):
        """Test successful highlight update."""
        service = ReadwiseService(api_token="test_token")

        mock_update_result = MagicMock()
        mock_update_result.success = True

        mock_pusher = MagicMock()
        mock_pusher.update = AsyncMock(return_value=mock_update_result)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("app.services.readwise.AsyncReadwiseClient", return_value=mock_client),
            patch("app.services.readwise.AsyncHighlightPusher", return_value=mock_pusher),
        ):
            result = await service.update_highlight(
                readwise_id="67890",
                text="Updated text",
                note="Updated note",
                page_number="50",
            )

        assert result.success is True
        assert result.readwise_id == "67890"
        assert result.error is None

    async def test_update_highlight_partial_update(self):
        """Test update_highlight with only some fields."""
        service = ReadwiseService(api_token="test_token")

        mock_update_result = MagicMock()
        mock_update_result.success = True

        mock_pusher = MagicMock()
        mock_pusher.update = AsyncMock(return_value=mock_update_result)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("app.services.readwise.AsyncReadwiseClient", return_value=mock_client),
            patch("app.services.readwise.AsyncHighlightPusher", return_value=mock_pusher),
        ):
            # Only update text, leave note and page_number as None
            result = await service.update_highlight(
                readwise_id="67890",
                text="Only text updated",
            )

        assert result.success is True

        # Verify update was called with only text
        mock_pusher.update.assert_called_once()
        call_kwargs = mock_pusher.update.call_args[1]
        assert call_kwargs.get("text") == "Only text updated"
        assert "note" not in call_kwargs
        assert "location" not in call_kwargs

    async def test_update_highlight_no_token(self):
        """Test update_highlight without token configured."""
        mock_settings = MagicMock()
        mock_settings.readwise_api_token = None
        with patch("app.services.readwise.get_settings", return_value=mock_settings):
            service = ReadwiseService(api_token=None)

            result = await service.update_highlight(
                readwise_id="67890",
                text="Test text",
            )

            assert result.success is False
            assert "not configured" in result.error

    async def test_update_highlight_no_fields(self):
        """Test update_highlight with no fields to update."""
        service = ReadwiseService(api_token="test_token")

        result = await service.update_highlight(
            readwise_id="67890",
        )

        assert result.success is False
        assert "No fields to update" in result.error

    async def test_update_highlight_api_error(self):
        """Test update_highlight with API error."""
        service = ReadwiseService(api_token="test_token")

        mock_update_result = MagicMock()
        mock_update_result.success = False
        mock_update_result.error = "Not found"

        mock_pusher = MagicMock()
        mock_pusher.update = AsyncMock(return_value=mock_update_result)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("app.services.readwise.AsyncReadwiseClient", return_value=mock_client),
            patch("app.services.readwise.AsyncHighlightPusher", return_value=mock_pusher),
        ):
            result = await service.update_highlight(
                readwise_id="99999",
                text="Test text",
            )

        assert result.success is False
        assert "Not found" in result.error

    async def test_update_highlight_network_error(self):
        """Test update_highlight with network error."""
        service = ReadwiseService(api_token="test_token")

        mock_pusher = MagicMock()
        mock_pusher.update = AsyncMock(side_effect=Exception("Connection failed"))

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("app.services.readwise.AsyncReadwiseClient", return_value=mock_client),
            patch("app.services.readwise.AsyncHighlightPusher", return_value=mock_pusher),
        ):
            result = await service.update_highlight(
                readwise_id="67890",
                text="Test text",
            )

        assert result.success is False
        assert "Error updating" in result.error

    async def test_update_highlight_clears_note(self):
        """Test update_highlight can clear a note by setting empty string."""
        service = ReadwiseService(api_token="test_token")

        mock_update_result = MagicMock()
        mock_update_result.success = True

        mock_pusher = MagicMock()
        mock_pusher.update = AsyncMock(return_value=mock_update_result)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("app.services.readwise.AsyncReadwiseClient", return_value=mock_client),
            patch("app.services.readwise.AsyncHighlightPusher", return_value=mock_pusher),
        ):
            result = await service.update_highlight(
                readwise_id="67890",
                note="",  # Empty string to clear note
            )

        assert result.success is True

        # Verify payload contains empty note
        call_kwargs = mock_pusher.update.call_args[1]
        assert call_kwargs.get("note") == ""


class TestSyncHighlightBackground:
    """Tests for the sync_highlight_background function."""

    async def test_sync_skipped_when_not_configured(self):
        """Test that sync is skipped when Readwise is not configured."""
        mock_service = MagicMock()
        mock_service.is_configured = False

        with patch("app.services.readwise._get_service", return_value=mock_service):
            await sync_highlight_background(
                highlight_id=1,
                book_title="Test Book",
                book_author="Test Author",
                text="Test text",
                note=None,
                page_number=None,
                created_at=datetime.now(tz=UTC),
            )

        # send_highlight should not be called since service is not configured
        mock_service.send_highlight.assert_not_called()

    async def test_sync_success_updates_database(self):
        """Test that successful sync updates the highlight in the database."""
        mock_service = MagicMock()
        mock_service.is_configured = True
        mock_service.send_highlight = AsyncMock(
            return_value=ReadwiseSyncResult(success=True, readwise_id="12345")
        )

        mock_highlight = MagicMock()
        mock_highlight.readwise_id = None
        mock_highlight.synced_at = None

        mock_db_result = MagicMock()
        mock_db_result.scalar_one_or_none.return_value = mock_highlight

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_db_result)

        with (
            patch("app.services.readwise._get_service", return_value=mock_service),
            patch("app.core.database.get_async_session") as mock_get_session,
        ):
            mock_get_session.return_value.__aenter__.return_value = mock_session

            await sync_highlight_background(
                highlight_id=1,
                book_title="Test Book",
                book_author="Test Author",
                text="Test text",
                note="A note",
                page_number="42",
                created_at=datetime.now(tz=UTC),
            )

        mock_service.send_highlight.assert_called_once()
        assert mock_highlight.readwise_id == "12345"
        assert mock_highlight.synced_at is not None

    async def test_sync_failure_does_not_update_database(self):
        """Test that failed sync does not update the highlight."""
        mock_service = MagicMock()
        mock_service.is_configured = True
        mock_service.send_highlight = AsyncMock(
            return_value=ReadwiseSyncResult(success=False, error="API error")
        )

        with patch("app.services.readwise._get_service", return_value=mock_service):
            # Should not raise, just log warning
            await sync_highlight_background(
                highlight_id=1,
                book_title="Test Book",
                book_author="Test Author",
                text="Test text",
                note=None,
                page_number=None,
                created_at=datetime.now(tz=UTC),
            )

        mock_service.send_highlight.assert_called_once()

    async def test_sync_exception_is_logged(self):
        """Test that exceptions during sync are caught and logged."""
        mock_service = MagicMock()
        mock_service.is_configured = True
        mock_service.send_highlight = AsyncMock(side_effect=Exception("Network error"))

        with patch("app.services.readwise._get_service", return_value=mock_service):
            # Should not raise, should catch and log
            await sync_highlight_background(
                highlight_id=1,
                book_title="Test Book",
                book_author="Test Author",
                text="Test text",
                note=None,
                page_number=None,
                created_at=datetime.now(tz=UTC),
            )
