"""Unit tests for database models."""

from app.models.book import Book
from app.models.highlight import Highlight


class TestBookModel:
    """Tests for the Book model."""

    async def test_create_book(self, test_session):
        """Test creating a book."""
        book = Book(
            title="The Great Gatsby",
            author="F. Scott Fitzgerald",
            isbn="9780743273565",
            cover_url="https://example.com/gatsby.jpg",
        )
        test_session.add(book)
        await test_session.flush()

        assert book.id is not None
        assert book.title == "The Great Gatsby"
        assert book.author == "F. Scott Fitzgerald"
        assert book.isbn == "9780743273565"
        assert book.created_at is not None

    async def test_create_book_minimal(self, test_session):
        """Test creating a book with minimal fields."""
        book = Book(title="Minimal Book", author="Unknown")
        test_session.add(book)
        await test_session.flush()

        assert book.id is not None
        assert book.title == "Minimal Book"
        assert book.author == "Unknown"
        assert book.isbn is None
        assert book.cover_url is None

    async def test_book_repr(self, sample_book):
        """Test book string representation."""
        repr_str = repr(sample_book)
        assert "Book" in repr_str
        assert "Test Book" in repr_str
        assert "Test Author" in repr_str

    async def test_book_highlights_relationship(self, test_session, sample_book):
        """Test book-highlights relationship."""
        highlight1 = Highlight(
            book_id=sample_book.id,
            text="First highlight",
        )
        highlight2 = Highlight(
            book_id=sample_book.id,
            text="Second highlight",
        )
        test_session.add_all([highlight1, highlight2])
        await test_session.flush()
        await test_session.refresh(sample_book)

        assert len(sample_book.highlights) == 2


class TestHighlightModel:
    """Tests for the Highlight model."""

    async def test_create_highlight(self, test_session, sample_book):
        """Test creating a highlight."""
        highlight = Highlight(
            book_id=sample_book.id,
            text="This is a meaningful quote from the book.",
            note="My thoughts on this passage.",
            page_number="123",
        )
        test_session.add(highlight)
        await test_session.flush()

        assert highlight.id is not None
        assert highlight.book_id == sample_book.id
        assert highlight.text == "This is a meaningful quote from the book."
        assert highlight.note == "My thoughts on this passage."
        assert highlight.page_number == "123"
        assert highlight.created_at is not None

    async def test_create_highlight_minimal(self, test_session, sample_book):
        """Test creating a highlight with minimal fields."""
        highlight = Highlight(
            book_id=sample_book.id,
            text="Simple highlight without note.",
        )
        test_session.add(highlight)
        await test_session.flush()

        assert highlight.id is not None
        assert highlight.note is None
        assert highlight.page_number is None

    async def test_highlight_book_relationship(self, test_session, sample_highlight):
        """Test highlight-book relationship."""
        await test_session.refresh(sample_highlight)
        assert sample_highlight.book is not None
        assert sample_highlight.book.title == "Test Book"

    async def test_cascade_delete_orphan_configured(self, sample_book):
        """Test that cascade delete-orphan is properly configured on book-highlights relationship.

        This verifies the ORM relationship configuration. The actual cascade behavior
        is tested in integration tests where full DB operations occur.
        """
        from app.models.book import Book

        # Check that the relationship has cascade configured
        mapper = Book.__mapper__
        highlights_rel = mapper.relationships["highlights"]

        # Verify cascade includes 'all' and 'delete-orphan'
        assert "delete" in highlights_rel.cascade
        assert "delete-orphan" in highlights_rel.cascade
