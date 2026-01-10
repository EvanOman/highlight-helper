"""Unit tests for services."""

from unittest.mock import AsyncMock, MagicMock, patch

from app.services.book_lookup import BookLookupService
from app.services.highlight_extractor import (
    ExtractedHighlight,
    HighlightExtractorService,
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
