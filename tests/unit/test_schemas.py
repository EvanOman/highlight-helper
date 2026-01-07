"""Unit tests for Pydantic schemas."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.api.schemas import (
    BookCreate,
    BookResponse,
    BookUpdate,
    ExtractHighlightRequest,
    HighlightCreate,
    HighlightResponse,
    HighlightUpdate,
)


class TestBookSchemas:
    """Tests for Book schemas."""

    def test_book_create_valid(self):
        """Test valid BookCreate schema."""
        book = BookCreate(
            title="Test Book",
            author="Test Author",
            isbn="1234567890",
            cover_url="https://example.com/cover.jpg",
        )
        assert book.title == "Test Book"
        assert book.author == "Test Author"
        assert book.isbn == "1234567890"

    def test_book_create_minimal(self):
        """Test BookCreate with minimal fields."""
        book = BookCreate(title="Minimal", author="Author")
        assert book.title == "Minimal"
        assert book.isbn is None
        assert book.cover_url is None

    def test_book_create_empty_title(self):
        """Test BookCreate with empty title fails."""
        with pytest.raises(ValidationError):
            BookCreate(title="", author="Author")

    def test_book_create_empty_author(self):
        """Test BookCreate with empty author fails."""
        with pytest.raises(ValidationError):
            BookCreate(title="Title", author="")

    def test_book_create_title_too_long(self):
        """Test BookCreate with title exceeding max length fails."""
        with pytest.raises(ValidationError):
            BookCreate(title="x" * 501, author="Author")

    def test_book_update_partial(self):
        """Test BookUpdate with partial fields."""
        update = BookUpdate(title="New Title")
        assert update.title == "New Title"
        assert update.author is None
        assert update.isbn is None

    def test_book_response_from_attributes(self):
        """Test BookResponse with from_attributes."""

        class MockBook:
            id = 1
            title = "Test Book"
            author = "Test Author"
            isbn = "1234567890"
            cover_url = "https://example.com/cover.jpg"
            created_at = datetime.now()

        response = BookResponse.model_validate(MockBook())
        assert response.id == 1
        assert response.title == "Test Book"


class TestHighlightSchemas:
    """Tests for Highlight schemas."""

    def test_highlight_create_valid(self):
        """Test valid HighlightCreate schema."""
        highlight = HighlightCreate(
            text="This is a highlight.",
            note="My note",
            page_number="42",
        )
        assert highlight.text == "This is a highlight."
        assert highlight.note == "My note"
        assert highlight.page_number == "42"

    def test_highlight_create_minimal(self):
        """Test HighlightCreate with minimal fields."""
        highlight = HighlightCreate(text="Just text")
        assert highlight.text == "Just text"
        assert highlight.note is None
        assert highlight.page_number is None

    def test_highlight_create_empty_text(self):
        """Test HighlightCreate with empty text fails."""
        with pytest.raises(ValidationError):
            HighlightCreate(text="")

    def test_highlight_update_partial(self):
        """Test HighlightUpdate with partial fields."""
        update = HighlightUpdate(note="Updated note")
        assert update.note == "Updated note"
        assert update.text is None
        assert update.page_number is None

    def test_highlight_response_from_attributes(self):
        """Test HighlightResponse with from_attributes."""

        class MockHighlight:
            id = 1
            book_id = 1
            text = "Test highlight"
            note = "Test note"
            page_number = "42"
            created_at = datetime.now()

        response = HighlightResponse.model_validate(MockHighlight())
        assert response.id == 1
        assert response.text == "Test highlight"


class TestExtractHighlightSchemas:
    """Tests for extraction-related schemas."""

    def test_extract_request_valid(self):
        """Test valid ExtractHighlightRequest."""
        request = ExtractHighlightRequest(instructions="Extract the highlighted text")
        assert request.instructions == "Extract the highlighted text"

    def test_extract_request_empty_instructions(self):
        """Test ExtractHighlightRequest with empty instructions fails."""
        with pytest.raises(ValidationError):
            ExtractHighlightRequest(instructions="")
