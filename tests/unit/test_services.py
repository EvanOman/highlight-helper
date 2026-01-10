"""Unit tests for services."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.services.book_lookup import BookLookupService
from app.services.highlight_extractor import (
    ExtractedHighlight,
    HighlightExtractorService,
)
from app.services.readwise import ReadwiseService


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
            text="Extracted text",
            confidence="high",
            page_number="42",
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

        assert result.text == "Extracted text"
        assert result.confidence == "high"
        assert result.page_number == "42"

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

        assert result.text == ""
        assert result.confidence == "low"
        assert result.page_number is None

    def test_extracted_highlight_model(self):
        """Test ExtractedHighlight Pydantic model."""
        # Test with all fields
        highlight = ExtractedHighlight(
            text="Some text",
            confidence="high",
            page_number="123",
        )
        assert highlight.text == "Some text"
        assert highlight.confidence == "high"
        assert highlight.page_number == "123"

        # Test with defaults
        highlight_default = ExtractedHighlight()
        assert highlight_default.text == ""
        assert highlight_default.confidence == "low"
        assert highlight_default.page_number is None

    def test_extracted_highlight_model_serialization(self):
        """Test ExtractedHighlight JSON serialization."""
        highlight = ExtractedHighlight(
            text="Test text",
            confidence="medium",
            page_number="42",
        )
        data = highlight.model_dump()
        assert data == {
            "text": "Test text",
            "confidence": "medium",
            "page_number": "42",
        }

    async def test_extract_highlight_with_instruction_based_request(self):
        """Test extraction with instruction-based request (not visual highlights)."""
        mock_lm = MagicMock()
        service = HighlightExtractorService(lm=mock_lm)

        mock_result = ExtractedHighlight(
            text="The sentence about love from the book",
            confidence="high",
            page_number="123",
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

        assert result.text == "The sentence about love from the book"
        assert result.confidence == "high"
        assert result.page_number == "123"


class TestReadwiseService:
    """Tests for the ReadwiseService."""

    def test_is_configured_without_token(self):
        """Test is_configured returns False without token."""
        service = ReadwiseService(api_token=None)
        assert service.is_configured is False

    def test_is_configured_with_token(self):
        """Test is_configured returns True with token."""
        service = ReadwiseService(api_token="test_token")
        assert service.is_configured is True

    async def test_validate_token_success(self):
        """Test successful token validation."""
        service = ReadwiseService(api_token="valid_token")

        mock_response = MagicMock()
        mock_response.status_code = 204

        with patch.object(service, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await service.validate_token()

        assert result is True

    async def test_validate_token_invalid(self):
        """Test token validation with invalid token."""
        service = ReadwiseService(api_token="invalid_token")

        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch.object(service, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await service.validate_token()

        assert result is False

    async def test_validate_token_no_token(self):
        """Test token validation without token configured."""
        service = ReadwiseService(api_token=None)
        result = await service.validate_token()
        assert result is False

    async def test_send_highlight_success(self):
        """Test successful highlight send."""
        service = ReadwiseService(api_token="test_token")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "id": 12345,
                "title": "Test Book",
                "modified_highlights": [67890],
            }
        ]

        with patch.object(service, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await service.send_highlight(
                text="Test highlight text",
                title="Test Book",
                author="Test Author",
                note="My note",
                page_number="42",
                highlighted_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )

        assert result.success is True
        assert result.readwise_id == "67890"
        assert result.error is None

    async def test_send_highlight_no_token(self):
        """Test send_highlight without token configured."""
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

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch.object(service, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await service.send_highlight(
                text="Test highlight",
                title="Test Book",
                author="Test Author",
            )

        assert result.success is False
        assert "500" in result.error

    async def test_send_highlight_network_error(self):
        """Test send_highlight with network error."""
        service = ReadwiseService(api_token="test_token")

        with patch.object(service, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.RequestError("Connection failed"))
            mock_get_client.return_value = mock_client

            result = await service.send_highlight(
                text="Test highlight",
                title="Test Book",
                author="Test Author",
            )

        assert result.success is False
        assert "Network error" in result.error

    async def test_send_highlights_batch_success(self):
        """Test successful batch highlight send."""
        service = ReadwiseService(api_token="test_token")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "id": 12345,
                "title": "Test Book",
                "modified_highlights": [111, 222],
            }
        ]

        with patch.object(service, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

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
        service = ReadwiseService(api_token=None)

        result = await service.send_highlights(
            [{"text": "Test", "title": "Book", "author": "Author"}]
        )

        assert result.total == 1
        assert result.synced == 0
        assert result.failed == 1
