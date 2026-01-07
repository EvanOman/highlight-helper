"""Unit tests for services."""

from unittest.mock import AsyncMock, MagicMock, patch

from app.services.book_lookup import BookLookupService
from app.services.highlight_extractor import HighlightExtractorService


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

    def test_encode_image_bytes(self):
        """Test encoding image bytes to base64."""
        service = HighlightExtractorService()
        test_bytes = b"test image data"
        encoded = service._encode_image_bytes(test_bytes)

        import base64

        decoded = base64.b64decode(encoded)
        assert decoded == test_bytes

    def test_get_image_media_type(self):
        """Test getting media type from filename."""
        service = HighlightExtractorService()

        assert service._get_image_media_type("photo.jpg") == "image/jpeg"
        assert service._get_image_media_type("photo.jpeg") == "image/jpeg"
        assert service._get_image_media_type("photo.png") == "image/png"
        assert service._get_image_media_type("photo.gif") == "image/gif"
        assert service._get_image_media_type("photo.webp") == "image/webp"
        assert service._get_image_media_type("photo.unknown") == "image/jpeg"

    async def test_extract_highlight_success(self):
        """Test successful highlight extraction."""
        service = HighlightExtractorService()

        mock_message = MagicMock()
        mock_message.content = (
            '{"text": "Extracted text", "confidence": "high", "page_number": "42"}'
        )

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        with patch.object(
            service._client.chat.completions, "create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_response

            result = await service.extract_highlight(
                image_bytes=b"fake image data",
                filename="test.jpg",
                instructions="Extract the highlighted text",
            )

        assert result.text == "Extracted text"
        assert result.confidence == "high"
        assert result.page_number == "42"

    async def test_extract_highlight_no_content(self):
        """Test highlight extraction with empty response."""
        service = HighlightExtractorService()

        mock_message = MagicMock()
        mock_message.content = None

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        with patch.object(
            service._client.chat.completions, "create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_response

            result = await service.extract_highlight(
                image_bytes=b"fake image data",
                filename="test.jpg",
                instructions="Extract the highlighted text",
            )

        assert result.text == ""
        assert result.confidence == "low"

    async def test_extract_highlight_invalid_json(self):
        """Test highlight extraction with invalid JSON response."""
        service = HighlightExtractorService()

        mock_message = MagicMock()
        mock_message.content = "This is not JSON"

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        with patch.object(
            service._client.chat.completions, "create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_response

            result = await service.extract_highlight(
                image_bytes=b"fake image data",
                filename="test.jpg",
                instructions="Extract the highlighted text",
            )

        assert result.text == "This is not JSON"
        assert result.confidence == "medium"

    async def test_extract_highlight_instruction_based(self):
        """Test instruction-based extraction without highlighted text."""
        service = HighlightExtractorService()

        mock_message = MagicMock()
        mock_message.content = (
            '{"text": "The sentence about love from the book", '
            '"confidence": "high", "page_number": "123"}'
        )

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        with patch.object(
            service._client.chat.completions, "create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_response

            result = await service.extract_highlight(
                image_bytes=b"fake image data",
                filename="test.jpg",
                instructions="grab the sentence about love",
            )

        assert result.text == "The sentence about love from the book"
        assert result.confidence == "high"
        assert result.page_number == "123"

        # Verify the API was called with appropriate messages
        mock_create.assert_called_once()
        call_args = mock_create.call_args
        messages = call_args.kwargs["messages"]

        # Check system prompt mentions instruction-based extraction
        system_content = messages[0]["content"]
        assert "INSTRUCTION-BASED" in system_content
        assert "grab the sentence about" in system_content

        # Check user message includes the instructions
        user_content = messages[1]["content"][0]["text"]
        assert "grab the sentence about love" in user_content
