"""Unit tests for services."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from readwise_sdk.v2.models import HighlightUpdate

from app.services.book_lookup import BookLookupService
from app.services.chat import ChatService
from app.services.chat_events import TextChunk, ToolUseFinished, ToolUseStarted
from app.services.highlight_extractor import (
    ExtractedHighlight,
    HighlightExtractorService,
)
from app.services.isbn_extractor import (
    ExtractedISBN,
    ISBNExtractorService,
)
from app.services.llm import LLMStream
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
        """Test ISBN search when book is not found in Google Books or Open Library."""
        service = BookLookupService()

        # Google Books returns no results
        mock_google_response = MagicMock()
        mock_google_response.json.return_value = {"totalItems": 0}
        mock_google_response.raise_for_status = MagicMock()

        # Open Library returns 404
        mock_ol_response = MagicMock()
        mock_ol_response.status_code = 404
        mock_ol_response.raise_for_status = MagicMock()

        with patch.object(service, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            # First call is Google Books, second is Open Library fallback
            mock_client.get = AsyncMock(side_effect=[mock_google_response, mock_ol_response])
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
        mock_prediction = MagicMock()
        mock_prediction.result = mock_result

        # Create an async function that returns our mock prediction
        async def mock_async_extract(*args, **kwargs):
            return mock_prediction

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
        # Typed failure: the error field distinguishes a model failure from a blank page.
        assert result.error is not None
        assert "API Error" in result.error

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
            "match_status": "not_found",
            "match_quality": 0.0,
            "error": None,
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
        mock_prediction = MagicMock()
        mock_prediction.result = mock_result

        async def mock_async_extract(*args, **kwargs):
            return mock_prediction

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
        mock_prediction = MagicMock()
        mock_prediction.result = mock_result

        async def mock_async_extract(*args, **kwargs):
            return mock_prediction

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
        mock_prediction = MagicMock()
        mock_prediction.result = mock_result

        async def mock_async_extract(*args, **kwargs):
            return mock_prediction

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

        # Verify update was called with a HighlightUpdate model
        mock_v2.update_highlight.assert_called_once()
        call_args = mock_v2.update_highlight.call_args[0]
        assert call_args[0] == 67890  # highlight_id
        update_model = call_args[1]
        assert isinstance(update_model, HighlightUpdate)
        assert update_model.text == "Only text updated"
        assert update_model.note is None
        assert update_model.location is None

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

        # Verify the HighlightUpdate model contains empty note
        call_args = mock_v2.update_highlight.call_args[0]
        update_model = call_args[1]
        assert isinstance(update_model, HighlightUpdate)
        assert update_model.note == ""

    async def test_update_highlight_uses_highlight_update_model(self):
        """Test that update_highlight constructs a HighlightUpdate model for the SDK."""
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

        # Verify the SDK was called with (highlight_id, HighlightUpdate)
        mock_v2.update_highlight.assert_called_once()
        call_args = mock_v2.update_highlight.call_args[0]
        assert call_args[0] == 67890
        update_model = call_args[1]
        assert isinstance(update_model, HighlightUpdate)
        assert update_model.text == "Updated text"
        assert update_model.note == "Updated note"
        assert update_model.location == 50


class TestSyncHighlightBackground:
    """Tests for the sync_highlight_background function."""

    async def test_sync_skipped_when_not_configured(self):
        """Test that sync is skipped when Readwise is not configured."""
        mock_service = MagicMock()
        mock_service.is_configured = False

        with patch("app.services.readwise.ReadwiseService", return_value=mock_service):
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
            patch("app.services.readwise.ReadwiseService", return_value=mock_service),
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

        with patch("app.services.readwise.ReadwiseService", return_value=mock_service):
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

        with patch("app.services.readwise.ReadwiseService", return_value=mock_service):
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


def _make_tool_call_delta(index, tool_id, func_name, arguments):
    """Create a mock tool call delta for LiteLLM streaming."""
    tc = MagicMock()
    tc.index = index
    tc.id = tool_id
    func = MagicMock()
    func.name = func_name
    func.arguments = arguments
    tc.function = func
    return tc


def _make_litellm_chunk(content=None, tool_calls=None, finish_reason=None, usage=None):
    """Create a mock LiteLLM streaming chunk."""
    chunk = MagicMock()
    delta = MagicMock()
    delta.content = content
    delta.tool_calls = tool_calls
    chunk.choices = [MagicMock(delta=delta, finish_reason=finish_reason)]
    chunk.usage = usage
    return chunk


# ---------------------------------------------------------------------------
# Gateway stream mocking helpers
# ---------------------------------------------------------------------------


class _FakeRawStream:
    """An async iterable over pre-built LiteLLM chunks."""

    def __init__(self, chunks):
        self._chunks = list(chunks)

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for c in self._chunks:
            yield c


class _GatewayStreamCM:
    """Async context manager mimicking llm_gateway.stream().

    Wraps chunks in a real ``LLMStream`` so that usage accumulation
    works identically to production code.
    """

    def __init__(self, chunks, model="anthropic/claude-haiku-4-5-20251001"):
        self._chunks = chunks
        self._model = model
        self._stream: LLMStream | None = None

    async def __aenter__(self):
        self._stream = LLMStream(_FakeRawStream(self._chunks), self._model)
        return self._stream

    async def __aexit__(self, *args):
        if self._stream is not None:
            self._stream._finalise()
        return False


def _make_gateway_stream(chunks, model="anthropic/claude-haiku-4-5-20251001"):
    """Build an async context manager wrapping chunks in a real LLMStream.

    Use as ``mock_stream.return_value = _make_gateway_stream(chunks)``
    or ``mock_stream.side_effect = [_make_gateway_stream(c1), ...]``.
    """
    return _GatewayStreamCM(chunks, model)


class TestChatService:
    """Tests for the ChatService metrics capture."""

    @patch("app.services.chat.llm_gateway.stream")
    async def test_last_metrics_populated_after_streaming(self, mock_stream):
        """Test that last_metrics is populated after streaming completes."""
        usage = MagicMock()
        usage.prompt_tokens = 100
        usage.completion_tokens = 50

        chunks = [
            _make_litellm_chunk(content="Hello"),
            _make_litellm_chunk(content=" world"),
            _make_litellm_chunk(finish_reason="stop", usage=usage),
        ]
        mock_stream.return_value = _make_gateway_stream(chunks)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_result.scalar.return_value = 0
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = ChatService(
            db=mock_db,
            chat_model="anthropic/claude-haiku-4-5-20251001",
        )

        events_out = [
            event
            async for event in service.send_message_from_history(
                history=[{"role": "user", "content": "Hello"}],
            )
        ]

        # Extract text from TextChunk events
        text_chunks = [e.text for e in events_out if isinstance(e, TextChunk)]
        assert text_chunks == ["Hello", " world"]
        assert service.last_metrics is not None
        assert service.last_metrics["model"] == "anthropic/claude-haiku-4-5-20251001"
        assert service.last_metrics["input_tokens"] == 100
        assert service.last_metrics["output_tokens"] == 50
        assert service.last_metrics["total_tokens"] == 150
        assert service.last_metrics["stop_reason"] == "stop"
        assert service.last_metrics["ttft_ms"] is not None
        assert service.last_metrics["total_latency_ms"] is not None
        assert service.last_metrics["tokens_per_sec"] is not None
        assert service.last_metrics["cost_usd"] is not None
        assert service.last_metrics["context_utilization_pct"] is not None

    @patch("app.services.chat.llm_gateway.stream")
    async def test_last_metrics_none_on_error(self, mock_stream):
        """Test that last_metrics stays None when stream errors."""
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(side_effect=Exception("API Error"))
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_stream.return_value = mock_cm

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_result.scalar.return_value = 0
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = ChatService(
            db=mock_db,
            chat_model="anthropic/claude-haiku-4-5-20251001",
        )

        events_out = [
            event
            async for event in service.send_message_from_history(
                history=[{"role": "user", "content": "Hello"}],
            )
        ]

        assert len(events_out) == 1
        assert isinstance(events_out[0], TextChunk)
        assert "error" in events_out[0].text.lower()
        assert service.last_metrics is None

    @patch("app.services.chat.llm_gateway.stream")
    async def test_tool_use_loop(self, mock_stream):
        """Test that tool_calls finish_reason triggers the tool loop and re-streams."""
        # -- First call: model requests a tool --
        tc_delta = _make_tool_call_delta(
            0, "tool_abc123", "search_highlights", '{"query": "leadership"}'
        )

        first_chunks = [
            _make_litellm_chunk(tool_calls=[tc_delta]),
            _make_litellm_chunk(finish_reason="tool_calls"),
        ]

        # -- Second call: model returns text --
        usage = MagicMock()
        usage.prompt_tokens = 200
        usage.completion_tokens = 60

        second_chunks = [
            _make_litellm_chunk(content="Here are "),
            _make_litellm_chunk(content="your results"),
            _make_litellm_chunk(finish_reason="stop", usage=usage),
        ]

        mock_stream.side_effect = [
            _make_gateway_stream(first_chunks),
            _make_gateway_stream(second_chunks),
        ]

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_result.scalar.return_value = 0
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = ChatService(
            db=mock_db,
            chat_model="anthropic/claude-haiku-4-5-20251001",
        )

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

        events_out = [
            event
            async for event in service.send_message_from_history(
                history=[{"role": "user", "content": "find highlights about leadership"}],
            )
        ]

        # Should have ToolUseStarted + ToolUseFinished events + TextChunk events
        tool_started = [e for e in events_out if isinstance(e, ToolUseStarted)]
        tool_finished = [e for e in events_out if isinstance(e, ToolUseFinished)]
        text_events = [e for e in events_out if isinstance(e, TextChunk)]

        assert len(tool_started) == 1
        assert tool_started[0].tool_name == "search_highlights"
        assert tool_started[0].tool_id == "tool_abc123"
        assert tool_started[0].tool_input == {"query": "leadership"}

        assert len(tool_finished) == 1
        assert tool_finished[0].tool_name == "search_highlights"
        assert "Found" in tool_finished[0].summary

        # Round separator ("\n\n") is yielded before round 2's text
        text_values = [e.text for e in text_events]
        assert text_values == ["\n\n", "Here are ", "your results"]

    @patch("app.services.chat.llm_gateway.stream")
    async def test_tool_messages_captured_for_persistence(self, mock_stream):
        """Test that tool_messages list is populated with serialized tool context."""
        import json

        # -- First call: model streams text then requests a tool --
        tc_delta = _make_tool_call_delta(
            0, "tool_abc123", "search_highlights", '{"query": "leadership"}'
        )

        first_chunks = [
            _make_litellm_chunk(content="Let me search..."),
            _make_litellm_chunk(tool_calls=[tc_delta]),
            _make_litellm_chunk(finish_reason="tool_calls"),
        ]

        # -- Second call: model returns text --
        second_chunks = [
            _make_litellm_chunk(content="Here are your results"),
            _make_litellm_chunk(finish_reason="stop"),
        ]

        mock_stream.side_effect = [
            _make_gateway_stream(first_chunks),
            _make_gateway_stream(second_chunks),
        ]

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_result.scalar.return_value = 0
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = ChatService(
            db=mock_db,
            chat_model="anthropic/claude-haiku-4-5-20251001",
        )
        service._search_repo = MagicMock()
        service._search_repo.search_highlights = AsyncMock(
            return_value=[{"id": 1, "text": "Leadership quote", "note": None}]
        )

        _ = [
            event
            async for event in service.send_message_from_history(
                history=[{"role": "user", "content": "find highlights about leadership"}],
            )
        ]

        assert len(service.tool_messages) == 2

        assistant_msg = service.tool_messages[0]
        assert assistant_msg["role"] == "assistant"
        blocks = assistant_msg["content_blocks"]
        assert len(blocks) == 2
        assert blocks[0] == {"type": "text", "text": "Let me search..."}
        assert blocks[1]["type"] == "tool_use"
        assert blocks[1]["id"] == "tool_abc123"
        assert blocks[1]["name"] == "search_highlights"
        assert blocks[1]["input"] == {"query": "leadership"}

        user_msg = service.tool_messages[1]
        assert user_msg["role"] == "user"
        result_blocks = user_msg["content_blocks"]
        assert len(result_blocks) == 1
        assert result_blocks[0]["type"] == "tool_result"
        assert result_blocks[0]["tool_use_id"] == "tool_abc123"
        parsed_result = json.loads(result_blocks[0]["content"])
        assert "highlights" in parsed_result

    @patch("app.services.chat.llm_gateway.stream")
    async def test_tool_messages_round_trip_as_json(self, mock_stream):
        """Test that tool_messages can be JSON-serialized and deserialized."""
        import json

        tc_delta = _make_tool_call_delta(0, "tool_xyz789", "search_books", '{"query": "fiction"}')

        first_chunks = [
            _make_litellm_chunk(tool_calls=[tc_delta]),
            _make_litellm_chunk(finish_reason="tool_calls"),
        ]

        second_chunks = [
            _make_litellm_chunk(content="Done"),
            _make_litellm_chunk(finish_reason="stop"),
        ]

        mock_stream.side_effect = [
            _make_gateway_stream(first_chunks),
            _make_gateway_stream(second_chunks),
        ]

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_result.scalar.return_value = 0
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = ChatService(
            db=mock_db,
            chat_model="anthropic/claude-haiku-4-5-20251001",
        )
        service._search_repo = MagicMock()
        service._search_repo.search_books = AsyncMock(
            return_value=[{"id": 1, "title": "A Novel", "author": "Auth"}]
        )

        _ = [
            event
            async for event in service.send_message_from_history(
                history=[{"role": "user", "content": "search for fiction books"}],
            )
        ]

        for tool_msg in service.tool_messages:
            serialized = json.dumps(tool_msg["content_blocks"])
            deserialized = json.loads(serialized)
            assert deserialized == tool_msg["content_blocks"]

            api_message = {"role": tool_msg["role"], "content": deserialized}
            assert api_message["role"] in ("assistant", "user")
            assert isinstance(api_message["content"], list)

    @patch("app.services.chat.llm_gateway.stream")
    async def test_no_tool_messages_for_plain_response(self, mock_stream):
        """Test that tool_messages is empty when no tools are used."""
        chunks = [
            _make_litellm_chunk(content="Hello"),
            _make_litellm_chunk(finish_reason="stop"),
        ]
        mock_stream.return_value = _make_gateway_stream(chunks)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_result.scalar.return_value = 0
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = ChatService(
            db=mock_db,
            chat_model="anthropic/claude-haiku-4-5-20251001",
        )

        _ = [
            event
            async for event in service.send_message_from_history(
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
            chat_model="claude-haiku-4-5-20251001",
        )
        mock_highlight = MagicMock()
        mock_highlight.text = "Some text"
        mock_highlight.note = "A note"
        mock_highlight.page_number = "10"

        service._highlight_repo = MagicMock()
        service._highlight_repo.list_for_book = AsyncMock(return_value=[mock_highlight])
        service._highlight_repo.count_for_book = AsyncMock(return_value=1)

        result = await service._execute_tool("get_book_highlights", {"book_id": 42})
        assert "highlights" in result
        assert len(result["highlights"]) == 1
        assert result["highlights"][0]["text"] == "Some text"
        assert "note" not in result  # nothing truncated
        service._highlight_repo.list_for_book.assert_called_once_with(42, limit=100)

    async def test_execute_tool_get_book_highlights_truncates(self):
        """Tool result notes truncation when a book exceeds the cap."""
        mock_db = AsyncMock()
        service = ChatService(db=mock_db, chat_model="claude-haiku-4-5-20251001")

        mock_highlight = MagicMock()
        mock_highlight.text = "Some text"
        mock_highlight.note = None
        mock_highlight.page_number = None

        service._highlight_repo = MagicMock()
        service._highlight_repo.list_for_book = AsyncMock(return_value=[mock_highlight] * 100)
        service._highlight_repo.count_for_book = AsyncMock(return_value=250)

        result = await service._execute_tool("get_book_highlights", {"book_id": 42})
        assert len(result["highlights"]) == 100
        assert "note" in result
        assert "250" in result["note"]

    async def test_execute_tool_unknown(self):
        """Test _execute_tool returns error for unknown tool."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = ChatService(
            db=mock_db,
            chat_model="claude-haiku-4-5-20251001",
        )

        result = await service._execute_tool("unknown_tool", {})
        assert "error" in result
        assert "unknown_tool" in result["error"].lower()
