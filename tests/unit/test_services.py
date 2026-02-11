"""Unit tests for services."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.book_lookup import BookLookupService
from app.services.chat import ChatService
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

        with (
            patch("app.services.highlight_extractor.dspy.Image"),
            patch(
                "app.services.highlight_extractor.dspy.asyncify",
                return_value=mock_async_extract,
            ),
            patch("app.services.highlight_extractor.dspy.context"),
        ):
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
        with (
            patch("app.services.highlight_extractor.dspy.Image"),
            patch(
                "app.services.highlight_extractor.dspy.asyncify",
                side_effect=Exception("API Error"),
            ),
            patch("app.services.highlight_extractor.dspy.context"),
        ):
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

        with (
            patch("app.services.highlight_extractor.dspy.Image"),
            patch(
                "app.services.highlight_extractor.dspy.asyncify",
                return_value=mock_async_extract,
            ),
            patch("app.services.highlight_extractor.dspy.context"),
        ):
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

        with (
            patch("app.services.isbn_extractor.dspy.Image"),
            patch(
                "app.services.isbn_extractor.dspy.asyncify",
                return_value=mock_async_extract,
            ),
            patch("app.services.isbn_extractor.dspy.context"),
        ):
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

        with (
            patch("app.services.isbn_extractor.dspy.Image"),
            patch(
                "app.services.isbn_extractor.dspy.asyncify",
                return_value=mock_async_extract,
            ),
            patch("app.services.isbn_extractor.dspy.context"),
        ):
            result = await service.extract_isbn(
                image_bytes=b"fake image data",
                filename="test.jpg",
            )

        assert result.isbn == "9781234567890"

    async def test_extract_isbn_error_fallback(self):
        """Test that errors during extraction return fallback response."""
        mock_lm = MagicMock()
        service = ISBNExtractorService(lm=mock_lm)

        with (
            patch("app.services.isbn_extractor.dspy.Image"),
            patch(
                "app.services.isbn_extractor.dspy.asyncify",
                side_effect=Exception("API Error"),
            ),
            patch("app.services.isbn_extractor.dspy.context"),
        ):
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
    """Tests for the ReadwiseService using the readwise-sdk."""

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

        mock_client = MagicMock()
        mock_client.validate_token = MagicMock(return_value=True)
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=None)

        with patch("app.services.readwise.ReadwiseClient", return_value=mock_client):
            result = await service.validate_token()

        assert result is True

    async def test_validate_token_invalid(self):
        """Test token validation with invalid token."""
        service = ReadwiseService(api_token="invalid_token")

        mock_client = MagicMock()
        mock_client.validate_token = MagicMock(return_value=False)
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=None)

        with patch("app.services.readwise.ReadwiseClient", return_value=mock_client):
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
        mock_pusher.push = MagicMock(return_value=mock_push_result)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=None)

        with (
            patch("app.services.readwise.ReadwiseClient", return_value=mock_client),
            patch("app.services.readwise.HighlightPusher", return_value=mock_pusher),
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
            assert result.error is not None
            assert "not configured" in result.error

    async def test_send_highlight_api_error(self):
        """Test send_highlight with API error."""
        service = ReadwiseService(api_token="test_token")

        # Mock a failed PushResult
        mock_push_result = MagicMock()
        mock_push_result.success = False
        mock_push_result.error = "API error: 500 Internal Server Error"

        mock_pusher = MagicMock()
        mock_pusher.push = MagicMock(return_value=mock_push_result)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=None)

        with (
            patch("app.services.readwise.ReadwiseClient", return_value=mock_client),
            patch("app.services.readwise.HighlightPusher", return_value=mock_pusher),
        ):
            result = await service.send_highlight(
                text="Test highlight",
                title="Test Book",
                author="Test Author",
            )

        assert result.success is False
        assert result.error is not None
        assert "API error" in result.error

    async def test_send_highlight_network_error(self):
        """Test send_highlight with network error."""
        service = ReadwiseService(api_token="test_token")

        mock_pusher = MagicMock()
        mock_pusher.push = MagicMock(side_effect=Exception("Connection failed"))

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=None)

        with (
            patch("app.services.readwise.ReadwiseClient", return_value=mock_client),
            patch("app.services.readwise.HighlightPusher", return_value=mock_pusher),
        ):
            result = await service.send_highlight(
                text="Test highlight",
                title="Test Book",
                author="Test Author",
            )

        assert result.success is False
        assert result.error is not None
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
        mock_pusher.push_batch = MagicMock(return_value=[mock_result_1, mock_result_2])

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=None)

        with (
            patch("app.services.readwise.ReadwiseClient", return_value=mock_client),
            patch("app.services.readwise.HighlightPusher", return_value=mock_pusher),
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

        mock_v2 = MagicMock()
        mock_v2.update_highlight = MagicMock(return_value=None)

        mock_client = MagicMock()
        mock_client.v2 = mock_v2
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=None)

        with patch("app.services.readwise.ReadwiseClient", return_value=mock_client):
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

        mock_v2 = MagicMock()
        mock_v2.update_highlight = MagicMock(return_value=None)

        mock_client = MagicMock()
        mock_client.v2 = mock_v2
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=None)

        with patch("app.services.readwise.ReadwiseClient", return_value=mock_client):
            # Only update text, leave note and page_number as None
            result = await service.update_highlight(
                readwise_id="67890",
                text="Only text updated",
            )

        assert result.success is True

        # Verify update was called with only text
        mock_v2.update_highlight.assert_called_once()
        call_kwargs = mock_v2.update_highlight.call_args[1]
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
            assert result.error is not None
            assert "not configured" in result.error

    async def test_update_highlight_no_fields(self):
        """Test update_highlight with no fields to update."""
        service = ReadwiseService(api_token="test_token")

        result = await service.update_highlight(
            readwise_id="67890",
        )

        assert result.success is False
        assert result.error is not None
        assert "No fields to update" in result.error

    async def test_update_highlight_api_error(self):
        """Test update_highlight with API error."""
        service = ReadwiseService(api_token="test_token")

        mock_v2 = MagicMock()
        mock_v2.update_highlight = MagicMock(side_effect=Exception("Not found"))

        mock_client = MagicMock()
        mock_client.v2 = mock_v2
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=None)

        with patch("app.services.readwise.ReadwiseClient", return_value=mock_client):
            result = await service.update_highlight(
                readwise_id="99999",
                text="Test text",
            )

        assert result.success is False
        assert result.error is not None
        assert "Not found" in result.error

    async def test_update_highlight_network_error(self):
        """Test update_highlight with network error."""
        service = ReadwiseService(api_token="test_token")

        mock_v2 = MagicMock()
        mock_v2.update_highlight = MagicMock(side_effect=Exception("Connection failed"))

        mock_client = MagicMock()
        mock_client.v2 = mock_v2
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=None)

        with patch("app.services.readwise.ReadwiseClient", return_value=mock_client):
            result = await service.update_highlight(
                readwise_id="67890",
                text="Test text",
            )

        assert result.success is False
        assert result.error is not None
        assert "Error updating" in result.error

    async def test_update_highlight_clears_note(self):
        """Test update_highlight can clear a note by setting empty string."""
        service = ReadwiseService(api_token="test_token")

        mock_v2 = MagicMock()
        mock_v2.update_highlight = MagicMock(return_value=None)

        mock_client = MagicMock()
        mock_client.v2 = mock_v2
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=None)

        with patch("app.services.readwise.ReadwiseClient", return_value=mock_client):
            result = await service.update_highlight(
                readwise_id="67890",
                note="",  # Empty string to clear note
            )

        assert result.success is True

        # Verify payload contains empty note
        call_kwargs = mock_v2.update_highlight.call_args[1]
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


def _make_text_delta_event(text_value):
    """Create a mock content_block_delta event with a text delta."""
    event = MagicMock()
    event.type = "content_block_delta"
    event.delta = MagicMock()
    event.delta.text = text_value
    # Ensure hasattr checks work correctly
    del event.delta.partial_json
    return event


def _make_mock_stream(events, final_message):
    """Create a mock stream context manager that yields events.

    The stream supports both ``async for event in stream`` iteration
    (used by the tool-use code path) and ``get_final_message()``.
    """

    class _MockStream:
        def __init__(self):
            self._events = list(events)
            self._final = final_message

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def __aiter__(self):
            return self._iter_events()

        async def _iter_events(self):
            for ev in self._events:
                yield ev

        async def get_final_message(self):
            return self._final

    return _MockStream()


class TestChatService:
    """Tests for the ChatService metrics capture."""

    async def test_last_metrics_populated_after_streaming(self):
        """Test that last_metrics is populated after streaming completes."""
        # Create a mock usage object
        mock_usage = MagicMock()
        mock_usage.input_tokens = 100
        mock_usage.output_tokens = 50

        # Create a mock final message
        mock_final_message = MagicMock()
        mock_final_message.usage = mock_usage
        mock_final_message.stop_reason = "end_turn"
        mock_final_message.content = [MagicMock(type="text", text="Hello world")]

        # Build events for the stream iterator
        events = [
            _make_text_delta_event("Hello"),
            _make_text_delta_event(" world"),
        ]

        mock_stream = _make_mock_stream(events, mock_final_message)

        # Create mock client
        mock_client = MagicMock()
        mock_client.messages.stream = MagicMock(return_value=mock_stream)

        # Create mock db session — scalar() returns 0 for count queries,
        # all() returns [] for list queries (used by _get_highlights_context)
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_result.scalar.return_value = 0
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = ChatService(
            db=mock_db,
            client=mock_client,
            chat_model="claude-haiku-4-5-20251001",
        )

        # Consume the generator
        chunks = [
            chunk
            async for chunk in service.send_message_from_history(
                history=[{"role": "user", "content": "Hello"}],
            )
        ]

        assert chunks == ["Hello", " world"]
        assert service.last_metrics is not None
        assert service.last_metrics["model"] == "claude-haiku-4-5-20251001"
        assert service.last_metrics["input_tokens"] == 100
        assert service.last_metrics["output_tokens"] == 50
        assert service.last_metrics["total_tokens"] == 150
        assert service.last_metrics["stop_reason"] == "end_turn"
        assert service.last_metrics["ttft_ms"] is not None
        assert service.last_metrics["total_latency_ms"] is not None
        assert service.last_metrics["tokens_per_sec"] is not None
        assert service.last_metrics["cost_usd"] is not None
        assert service.last_metrics["context_utilization_pct"] is not None

    async def test_last_metrics_none_on_error(self):
        """Test that last_metrics stays None when stream errors."""
        # Create a mock stream that raises
        mock_stream = MagicMock()
        mock_stream.__aenter__ = AsyncMock(side_effect=Exception("API Error"))
        mock_stream.__aexit__ = AsyncMock(return_value=False)

        mock_client = MagicMock()
        mock_client.messages.stream = MagicMock(return_value=mock_stream)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_result.scalar.return_value = 0
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = ChatService(
            db=mock_db,
            client=mock_client,
            chat_model="claude-haiku-4-5-20251001",
        )

        chunks = [
            chunk
            async for chunk in service.send_message_from_history(
                history=[{"role": "user", "content": "Hello"}],
            )
        ]

        assert len(chunks) == 1
        assert "error" in chunks[0].lower()
        assert service.last_metrics is None

    async def test_tool_use_loop(self):
        """Test that tool_use stop_reason triggers the tool loop and re-streams."""
        import json

        # -- First call: model requests a tool --
        tool_use_block = MagicMock()
        tool_use_block.type = "tool_use"
        tool_use_block.name = "search_highlights"
        tool_use_block.input = {"query": "leadership"}
        tool_use_block.id = "tool_abc123"

        first_usage = MagicMock()
        first_usage.input_tokens = 80
        first_usage.output_tokens = 20

        first_final = MagicMock()
        first_final.usage = first_usage
        first_final.stop_reason = "tool_use"
        first_final.content = [tool_use_block]

        first_stream = _make_mock_stream([], first_final)

        # -- Second call: model returns text after getting tool results --
        second_usage = MagicMock()
        second_usage.input_tokens = 120
        second_usage.output_tokens = 40

        second_final = MagicMock()
        second_final.usage = second_usage
        second_final.stop_reason = "end_turn"
        second_final.content = [MagicMock(type="text", text="Here are your results")]

        second_events = [
            _make_text_delta_event("Here are "),
            _make_text_delta_event("your results"),
        ]
        second_stream = _make_mock_stream(second_events, second_final)

        # Set up client to return first_stream then second_stream
        mock_client = MagicMock()
        mock_client.messages.stream = MagicMock(side_effect=[first_stream, second_stream])

        # Mock DB — scalar() returns 0 for count queries
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_result.scalar.return_value = 0
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = ChatService(
            db=mock_db,
            client=mock_client,
            chat_model="claude-haiku-4-5-20251001",
        )

        # Mock the search repository to return results
        service._search_repo = MagicMock()
        service._search_repo.search_highlights = AsyncMock(
            return_value=[
                {
                    "id": 1,
                    "book_id": 1,
                    "text": "Leadership is about influence",
                    "note": None,
                    "book_title": "Leadership Book",
                    "book_author": "Author",
                    "rank": -1.5,
                    "snippet": "Leadership is about influence",
                }
            ]
        )

        chunks = [
            chunk
            async for chunk in service.send_message_from_history(
                history=[{"role": "user", "content": "find highlights about leadership"}],
            )
        ]

        # Should have tool_use + tool_done markers + text chunks
        tool_use_chunks = [c for c in chunks if c.startswith("__tool_use__:")]
        tool_done_chunks = [c for c in chunks if c.startswith("__tool_done__:")]
        text_chunks = [
            c
            for c in chunks
            if not c.startswith("__tool_use__:") and not c.startswith("__tool_done__:")
        ]

        assert len(tool_use_chunks) == 1
        tool_data = json.loads(tool_use_chunks[0].replace("__tool_use__:", ""))
        assert tool_data["tool"] == "search_highlights"

        assert len(tool_done_chunks) == 1
        done_data = json.loads(tool_done_chunks[0].replace("__tool_done__:", ""))
        assert done_data["tool"] == "search_highlights"
        assert "Found" in done_data["summary"]

        # Round separator ("\n\n") is yielded before round 2's text
        assert text_chunks == ["\n\n", "Here are ", "your results"]

        # Metrics should aggregate both calls
        assert service.last_metrics is not None
        assert service.last_metrics["input_tokens"] == 200  # 80 + 120
        assert service.last_metrics["output_tokens"] == 60  # 20 + 40

    async def test_tool_messages_captured_for_persistence(self):
        """Test that tool_messages list is populated with serialized tool context.

        After a tool-use round, the service should expose serialized
        assistant (tool_use) and user (tool_result) messages so the API
        layer can persist them for conversation history reconstruction.
        """
        import json

        # -- First call: model requests a tool --
        tool_use_block = MagicMock()
        tool_use_block.type = "tool_use"
        tool_use_block.name = "search_highlights"
        tool_use_block.input = {"query": "leadership"}
        tool_use_block.id = "tool_abc123"

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Let me search..."

        first_usage = MagicMock()
        first_usage.input_tokens = 80
        first_usage.output_tokens = 20

        first_final = MagicMock()
        first_final.usage = first_usage
        first_final.stop_reason = "tool_use"
        first_final.content = [text_block, tool_use_block]

        first_stream = _make_mock_stream([_make_text_delta_event("Let me search...")], first_final)

        # -- Second call: model returns text --
        second_usage = MagicMock()
        second_usage.input_tokens = 120
        second_usage.output_tokens = 40

        second_final = MagicMock()
        second_final.usage = second_usage
        second_final.stop_reason = "end_turn"
        second_final.content = [MagicMock(type="text", text="Here are your results")]

        second_events = [_make_text_delta_event("Here are your results")]
        second_stream = _make_mock_stream(second_events, second_final)

        mock_client = MagicMock()
        mock_client.messages.stream = MagicMock(side_effect=[first_stream, second_stream])

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_result.scalar.return_value = 0
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = ChatService(
            db=mock_db,
            client=mock_client,
            chat_model="claude-haiku-4-5-20251001",
        )
        service._search_repo = MagicMock()
        service._search_repo.search_highlights = AsyncMock(
            return_value=[{"id": 1, "text": "Leadership quote", "note": None}]
        )

        # Consume the generator
        _ = [
            chunk
            async for chunk in service.send_message_from_history(
                history=[{"role": "user", "content": "find highlights about leadership"}],
            )
        ]

        # tool_messages should have exactly 2 entries: assistant tool_use + user tool_result
        assert len(service.tool_messages) == 2

        # First: assistant message with serialized content_blocks
        assistant_msg = service.tool_messages[0]
        assert assistant_msg["role"] == "assistant"
        blocks = assistant_msg["content_blocks"]
        assert len(blocks) == 2
        assert blocks[0] == {"type": "text", "text": "Let me search..."}
        assert blocks[1]["type"] == "tool_use"
        assert blocks[1]["id"] == "tool_abc123"
        assert blocks[1]["name"] == "search_highlights"
        assert blocks[1]["input"] == {"query": "leadership"}

        # Second: user message with tool_result content_blocks
        user_msg = service.tool_messages[1]
        assert user_msg["role"] == "user"
        result_blocks = user_msg["content_blocks"]
        assert len(result_blocks) == 1
        assert result_blocks[0]["type"] == "tool_result"
        assert result_blocks[0]["tool_use_id"] == "tool_abc123"
        # The tool result content is JSON-encoded
        parsed_result = json.loads(result_blocks[0]["content"])
        assert "highlights" in parsed_result

    async def test_tool_messages_round_trip_as_json(self):
        """Test that tool_messages can be JSON-serialized and deserialized.

        This verifies the data is suitable for storage in the content_blocks
        column and reconstruction into Anthropic API message format.
        """
        import json

        # -- First call: model requests a tool --
        tool_use_block = MagicMock()
        tool_use_block.type = "tool_use"
        tool_use_block.name = "search_books"
        tool_use_block.input = {"query": "fiction"}
        tool_use_block.id = "tool_xyz789"

        first_usage = MagicMock()
        first_usage.input_tokens = 50
        first_usage.output_tokens = 15

        first_final = MagicMock()
        first_final.usage = first_usage
        first_final.stop_reason = "tool_use"
        first_final.content = [tool_use_block]

        first_stream = _make_mock_stream([], first_final)

        # -- Second call: model returns text --
        second_usage = MagicMock()
        second_usage.input_tokens = 100
        second_usage.output_tokens = 30

        second_final = MagicMock()
        second_final.usage = second_usage
        second_final.stop_reason = "end_turn"
        second_final.content = [MagicMock(type="text", text="Done")]

        second_stream = _make_mock_stream([_make_text_delta_event("Done")], second_final)

        mock_client = MagicMock()
        mock_client.messages.stream = MagicMock(side_effect=[first_stream, second_stream])

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_result.scalar.return_value = 0
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = ChatService(
            db=mock_db,
            client=mock_client,
            chat_model="claude-haiku-4-5-20251001",
        )
        service._search_repo = MagicMock()
        service._search_repo.search_books = AsyncMock(
            return_value=[{"id": 1, "title": "A Novel", "author": "Auth"}]
        )

        _ = [
            chunk
            async for chunk in service.send_message_from_history(
                history=[{"role": "user", "content": "search for fiction books"}],
            )
        ]

        # Simulate the round-trip: serialize to JSON (as the DB would store) and deserialize
        for tool_msg in service.tool_messages:
            serialized = json.dumps(tool_msg["content_blocks"])
            deserialized = json.loads(serialized)

            # Deserialized should match original
            assert deserialized == tool_msg["content_blocks"]

            # Verify it can be used as Anthropic API content
            api_message = {"role": tool_msg["role"], "content": deserialized}
            assert api_message["role"] in ("assistant", "user")
            assert isinstance(api_message["content"], list)

    async def test_no_tool_messages_for_plain_response(self):
        """Test that tool_messages is empty when no tools are used."""
        mock_usage = MagicMock()
        mock_usage.input_tokens = 100
        mock_usage.output_tokens = 50

        mock_final_message = MagicMock()
        mock_final_message.usage = mock_usage
        mock_final_message.stop_reason = "end_turn"
        mock_final_message.content = [MagicMock(type="text", text="Hello")]

        events = [_make_text_delta_event("Hello")]
        mock_stream = _make_mock_stream(events, mock_final_message)

        mock_client = MagicMock()
        mock_client.messages.stream = MagicMock(return_value=mock_stream)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_result.scalar.return_value = 0
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = ChatService(
            db=mock_db,
            client=mock_client,
            chat_model="claude-haiku-4-5-20251001",
        )

        _ = [
            chunk
            async for chunk in service.send_message_from_history(
                history=[{"role": "user", "content": "Hello"}],
            )
        ]

        assert service.tool_messages == []

    async def test_execute_tool_search_books(self):
        """Test _execute_tool dispatches search_books correctly."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = ChatService(
            db=mock_db,
            client=MagicMock(),
            chat_model="claude-haiku-4-5-20251001",
        )
        service._search_repo = MagicMock()
        service._search_repo.search_books = AsyncMock(
            return_value=[{"id": 1, "title": "Book", "author": "Auth", "rank": -1, "snippet": ""}]
        )

        result = await service._execute_tool("search_books", {"query": "test"})
        assert "books" in result
        assert len(result["books"]) == 1
        service._search_repo.search_books.assert_called_once_with("test")

    async def test_execute_tool_search_highlights(self):
        """Test _execute_tool dispatches search_highlights correctly."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = ChatService(
            db=mock_db,
            client=MagicMock(),
            chat_model="claude-haiku-4-5-20251001",
        )
        service._search_repo = MagicMock()
        service._search_repo.search_highlights = AsyncMock(return_value=[])

        result = await service._execute_tool("search_highlights", {"query": "topic"})
        assert "highlights" in result
        service._search_repo.search_highlights.assert_called_once_with("topic", limit=20)

    async def test_execute_tool_get_book_highlights(self):
        """Test _execute_tool dispatches get_book_highlights correctly."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = ChatService(
            db=mock_db,
            client=MagicMock(),
            chat_model="claude-haiku-4-5-20251001",
        )
        mock_highlight = MagicMock()
        mock_highlight.text = "Some text"
        mock_highlight.note = "A note"
        mock_highlight.page_number = "10"

        service._highlight_repo = MagicMock()
        service._highlight_repo.list_for_book = AsyncMock(return_value=[mock_highlight])

        result = await service._execute_tool("get_book_highlights", {"book_id": 42})
        assert "highlights" in result
        assert len(result["highlights"]) == 1
        assert result["highlights"][0]["text"] == "Some text"
        service._highlight_repo.list_for_book.assert_called_once_with(42)

    async def test_execute_tool_unknown(self):
        """Test _execute_tool returns error for unknown tool."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = ChatService(
            db=mock_db,
            client=MagicMock(),
            chat_model="claude-haiku-4-5-20251001",
        )

        result = await service._execute_tool("unknown_tool", {})
        assert "error" in result
        assert "unknown_tool" in result["error"].lower()


class TestSerializeContentBlocks:
    """Tests for the _serialize_content_blocks helper."""

    def test_serialize_text_block(self):
        """Test serializing a text content block."""
        from app.services.chat import _serialize_content_blocks

        block = MagicMock()
        block.type = "text"
        block.text = "Hello world"

        result = _serialize_content_blocks([block])
        assert result == [{"type": "text", "text": "Hello world"}]

    def test_serialize_tool_use_block(self):
        """Test serializing a tool_use content block."""
        from app.services.chat import _serialize_content_blocks

        block = MagicMock()
        block.type = "tool_use"
        block.id = "tool_123"
        block.name = "search_highlights"
        block.input = {"query": "leadership"}

        result = _serialize_content_blocks([block])
        assert result == [
            {
                "type": "tool_use",
                "id": "tool_123",
                "name": "search_highlights",
                "input": {"query": "leadership"},
            }
        ]

    def test_serialize_mixed_blocks(self):
        """Test serializing a mix of text and tool_use blocks."""
        from app.services.chat import _serialize_content_blocks

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Let me search for that."

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.id = "tool_456"
        tool_block.name = "search_books"
        tool_block.input = {"query": "fiction"}

        result = _serialize_content_blocks([text_block, tool_block])
        assert len(result) == 2
        assert result[0] == {"type": "text", "text": "Let me search for that."}
        assert result[1]["type"] == "tool_use"
        assert result[1]["name"] == "search_books"

    def test_serialize_dict_passthrough(self):
        """Test that plain dicts are passed through unchanged."""
        from app.services.chat import _serialize_content_blocks

        block = {"type": "tool_result", "tool_use_id": "tool_123", "content": "{}"}

        result = _serialize_content_blocks([block])
        assert result == [block]

    def test_serialize_empty_list(self):
        """Test serializing an empty list."""
        from app.services.chat import _serialize_content_blocks

        result = _serialize_content_blocks([])
        assert result == []
