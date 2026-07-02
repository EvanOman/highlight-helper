"""Unit tests for ReadwiseService.sync_down() and related methods."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, Mock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base, create_fts_and_indexes
from app.models.book import Book
from app.models.highlight import AnnotationType, Highlight, SyncStatus
from app.services.readwise import (
    ReadwiseBook,
    ReadwiseHighlight,
    ReadwiseService,
    SyncDownProgress,
)

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_engine():
    """Create a test database engine with full schema including migrations."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(create_fts_and_indexes)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine):
    """Create a test database session."""
    maker = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_export_highlight(
    *,
    id: int,
    text: str,
    note: str | None = None,
    location: int | None = None,
    highlighted_at: datetime | None = None,
) -> MagicMock:
    """Create a mock export highlight object matching the Readwise SDK shape."""
    h = MagicMock()
    h.id = id
    h.text = text
    h.note = note
    h.location = location
    h.highlighted_at = highlighted_at or datetime(2024, 6, 15, tzinfo=UTC)
    return h


def _make_export_book(
    *,
    user_book_id: int,
    title: str | None,
    author: str | None,
    category: str = "books",
    cover_image_url: str | None = None,
    highlights: list | None = None,
) -> MagicMock:
    """Create a mock ExportBook object matching the Readwise SDK shape."""
    book = MagicMock()
    book.user_book_id = user_book_id
    book.title = title
    book.author = author
    book.category = category
    book.cover_image_url = cover_image_url
    book.highlights = highlights or []
    return book


async def _collect_events(
    service: ReadwiseService, db_session: AsyncSession
) -> list[SyncDownProgress]:
    """Collect all SyncDownProgress events from sync_down into a list."""
    return [event async for event in service.sync_down(db_session)]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSyncDownUnconfigured:
    """Tests for sync_down when Readwise is not configured."""

    async def test_unconfigured_yields_complete_with_error(self, db_session):
        """sync_down with no API token yields a single complete event with error."""
        mock_settings = MagicMock()
        mock_settings.readwise_api_token = None
        with patch("app.services.readwise.get_settings", return_value=mock_settings):
            service = ReadwiseService(api_token=None)

        events = await _collect_events(service, db_session)

        assert len(events) == 1
        assert events[0].phase == "complete"
        assert len(events[0].errors) > 0
        assert "not configured" in events[0].errors[0].lower()

    async def test_unconfigured_empty_string_token(self, db_session):
        """sync_down with empty-string token is treated as unconfigured."""
        service = ReadwiseService(api_token="")

        events = await _collect_events(service, db_session)

        assert len(events) == 1
        assert events[0].phase == "complete"
        assert len(events[0].errors) > 0


class TestSyncDownSuccessful:
    """Tests for a successful sync_down import with mocked Readwise SDK."""

    @pytest.fixture
    def mock_export_data(self):
        """Two books with highlights as mock ExportBook objects."""
        h1a = _make_export_highlight(id=101, text="First highlight of book 1")
        h1b = _make_export_highlight(
            id=102, text="Second highlight of book 1", note="A note", location=42
        )
        h2a = _make_export_highlight(id=201, text="Only highlight of book 2")

        book1 = _make_export_book(
            user_book_id=1,
            title="Effective Python",
            author="Brett Slatkin",
            cover_image_url="https://example.com/cover1.jpg",
            highlights=[h1a, h1b],
        )
        book2 = _make_export_book(
            user_book_id=2,
            title="Designing Data-Intensive Applications",
            author="Martin Kleppmann",
            highlights=[h2a],
        )
        return [book1, book2]

    @pytest.fixture
    def service_with_mock_client(self, mock_export_data):
        """ReadwiseService whose _create_client returns a mock client."""
        service = ReadwiseService(api_token="test_token")

        mock_client = MagicMock()
        mock_client.v2.export_highlights.return_value = iter(mock_export_data)
        mock_client.close = MagicMock()

        with patch.object(service, "_create_client", return_value=mock_client):
            yield service

    async def test_yields_fetching_then_processing_then_complete(
        self, service_with_mock_client, db_session
    ):
        """sync_down yields fetching -> processing (per book) -> complete."""
        events = await _collect_events(service_with_mock_client, db_session)

        phases = [e.phase for e in events]
        # First event is always "fetching"
        assert phases[0] == "fetching"
        # Last event is always "complete"
        assert phases[-1] == "complete"
        # There should be "processing" events in between
        assert "processing" in phases

    async def test_books_created_in_db(self, service_with_mock_client, db_session):
        """sync_down creates Book rows in the database."""
        await _collect_events(service_with_mock_client, db_session)
        await db_session.flush()

        result = await db_session.execute(select(Book))
        books = result.scalars().all()

        assert len(books) == 2
        titles = {b.title for b in books}
        assert "Effective Python" in titles
        assert "Designing Data-Intensive Applications" in titles

    async def test_highlights_created_with_correct_fields(
        self, service_with_mock_client, db_session
    ):
        """sync_down creates Highlight rows with readwise_id, sync_status=SYNCED, etc."""
        await _collect_events(service_with_mock_client, db_session)
        await db_session.flush()

        result = await db_session.execute(select(Highlight))
        highlights = result.scalars().all()

        assert len(highlights) == 3

        for h in highlights:
            assert h.readwise_id is not None
            assert h.sync_status == SyncStatus.SYNCED
            assert h.synced_at is not None
            assert h.type == AnnotationType.HIGHLIGHT

        # Check specific fields on the highlight with a note and location
        noted_highlight = next(h for h in highlights if h.note == "A note")
        assert noted_highlight.page_number == "42"
        assert noted_highlight.readwise_id == "102"

    async def test_final_complete_counts_accurate(self, service_with_mock_client, db_session):
        """The final complete event has accurate counts."""
        events = await _collect_events(service_with_mock_client, db_session)

        complete = events[-1]
        assert complete.phase == "complete"
        assert complete.books_processed == 2
        assert complete.books_total == 2
        assert complete.highlights_imported == 3
        assert complete.highlights_skipped == 0
        assert complete.errors == []

    async def test_book_cover_url_saved(self, service_with_mock_client, db_session):
        """Book cover_url is persisted to the database."""
        await _collect_events(service_with_mock_client, db_session)
        await db_session.flush()

        result = await db_session.execute(select(Book).where(Book.title == "Effective Python"))
        book = result.scalar_one()
        assert book.cover_url == "https://example.com/cover1.jpg"


class TestSyncDownDuplicates:
    """Tests for sync_down duplicate handling."""

    async def test_duplicate_readwise_id_skipped(self, db_session):
        """Pre-existing highlight with same readwise_id is skipped."""
        # Pre-insert a book and highlight with readwise_id="101"
        book = Book(title="Effective Python", author="Brett Slatkin")
        db_session.add(book)
        await db_session.flush()

        existing = Highlight(
            book_id=book.id,
            text="First highlight of book 1",
            readwise_id="101",
            sync_status=SyncStatus.SYNCED,
            synced_at=datetime.now(tz=UTC),
        )
        db_session.add(existing)
        await db_session.flush()

        # Mock export returning the same highlight plus a new one
        h1 = _make_export_highlight(id=101, text="First highlight of book 1")
        h2 = _make_export_highlight(id=999, text="A new highlight")
        export_book = _make_export_book(
            user_book_id=1,
            title="Effective Python",
            author="Brett Slatkin",
            highlights=[h1, h2],
        )

        service = ReadwiseService(api_token="test_token")
        mock_client = MagicMock()
        mock_client.v2.export_highlights.return_value = iter([export_book])
        mock_client.close = MagicMock()

        with patch.object(service, "_create_client", return_value=mock_client):
            events = await _collect_events(service, db_session)

        complete = events[-1]
        assert complete.highlights_skipped == 1
        assert complete.highlights_imported == 1

        # Verify total highlights: 1 existing + 1 new = 2
        result = await db_session.execute(select(Highlight))
        all_highlights = result.scalars().all()
        assert len(all_highlights) == 2


class TestSyncDownEmptyLibrary:
    """Tests for sync_down with an empty Readwise library."""

    async def test_empty_library_yields_complete_with_no_books(self, db_session):
        """Empty library yields a complete event with zero counts."""
        service = ReadwiseService(api_token="test_token")
        mock_client = MagicMock()
        mock_client.v2.export_highlights.return_value = iter([])
        mock_client.close = MagicMock()

        with patch.object(service, "_create_client", return_value=mock_client):
            events = await _collect_events(service, db_session)

        # Should have at least fetching + complete
        phases = [e.phase for e in events]
        assert "fetching" in phases
        assert phases[-1] == "complete"

        complete = events[-1]
        assert complete.books_processed == 0
        assert complete.highlights_imported == 0
        assert complete.highlights_skipped == 0
        assert "No books found" in complete.message


class TestSyncDownFetchError:
    """Tests for sync_down when fetching from Readwise fails."""

    async def test_fetch_exception_yields_error_event(self, db_session):
        """When the SDK raises during fetch, sync_down yields an error complete event."""
        service = ReadwiseService(api_token="test_token")
        mock_client = MagicMock()
        mock_client.v2.export_highlights.side_effect = ConnectionError("Network timeout")
        mock_client.close = MagicMock()

        with patch.object(service, "_create_client", return_value=mock_client):
            events = await _collect_events(service, db_session)

        # The last event should be a complete event with error info
        complete = events[-1]
        assert complete.phase == "complete"
        assert len(complete.errors) > 0
        error_text = " ".join(complete.errors).lower()
        assert "fetch" in error_text or "network" in error_text

    async def test_fetch_books_propagates_exception(self):
        """fetch_books() propagates exceptions from the SDK."""
        service = ReadwiseService(api_token="test_token")
        mock_client = MagicMock()
        mock_client.v2.export_highlights.side_effect = RuntimeError("API 500")
        mock_client.close = MagicMock()

        with (
            patch.object(service, "_create_client", return_value=mock_client),
            pytest.raises(RuntimeError, match="API 500"),
        ):
            await service.fetch_books()


class TestSyncDownExistingBook:
    """Tests for sync_down when the book already exists in the database."""

    async def test_reuses_existing_book(self, db_session):
        """sync_down reuses an existing book with same title+author instead of creating a duplicate."""
        # Pre-insert the book
        existing_book = Book(
            title="Effective Python",
            author="Brett Slatkin",
            isbn="1234567890",
        )
        db_session.add(existing_book)
        await db_session.flush()
        existing_book_id = existing_book.id

        # Mock export with same title+author
        h1 = _make_export_highlight(id=301, text="A highlight from Readwise")
        export_book = _make_export_book(
            user_book_id=10,
            title="Effective Python",
            author="Brett Slatkin",
            highlights=[h1],
        )

        service = ReadwiseService(api_token="test_token")
        mock_client = MagicMock()
        mock_client.v2.export_highlights.return_value = iter([export_book])
        mock_client.close = MagicMock()

        with patch.object(service, "_create_client", return_value=mock_client):
            events = await _collect_events(service, db_session)

        complete = events[-1]
        assert complete.highlights_imported == 1

        # Verify only one book exists
        result = await db_session.execute(select(Book))
        books = result.scalars().all()
        assert len(books) == 1
        assert books[0].id == existing_book_id

        # Verify the highlight is linked to the existing book
        h_result = await db_session.execute(select(Highlight))
        highlights = h_result.scalars().all()
        assert len(highlights) == 1
        assert highlights[0].book_id == existing_book_id


class TestSyncDownBooksWithNoHighlights:
    """Tests for sync_down skipping books with empty highlights."""

    async def test_books_with_no_highlights_skipped(self, db_session):
        """Books with empty highlights lists are skipped (no Book row created)."""
        empty_book = _make_export_book(
            user_book_id=1,
            title="Empty Book",
            author="No Highlights Author",
            highlights=[],
        )
        h1 = _make_export_highlight(id=501, text="A real highlight")
        normal_book = _make_export_book(
            user_book_id=2,
            title="Normal Book",
            author="Has Highlights Author",
            highlights=[h1],
        )

        service = ReadwiseService(api_token="test_token")
        mock_client = MagicMock()
        mock_client.v2.export_highlights.return_value = iter([empty_book, normal_book])
        mock_client.close = MagicMock()

        with patch.object(service, "_create_client", return_value=mock_client):
            events = await _collect_events(service, db_session)

        complete = events[-1]
        assert complete.phase == "complete"
        # Both books are "processed" (the empty one increments the counter)
        assert complete.books_processed == 2
        assert complete.highlights_imported == 1

        # Only the book with highlights should have been created in the DB
        result = await db_session.execute(select(Book))
        books = result.scalars().all()
        assert len(books) == 1
        assert books[0].title == "Normal Book"


class TestSyncDownNonBooksFiltered:
    """Tests for sync_down filtering non-book categories."""

    async def test_non_book_categories_filtered_out(self, db_session):
        """fetch_books and sync_down filter out items whose category is not 'books'."""
        h1 = _make_export_highlight(id=601, text="Article highlight")
        article = _make_export_book(
            user_book_id=1,
            title="Some Article",
            author="Blogger",
            category="articles",
            highlights=[h1],
        )
        h2 = _make_export_highlight(id=602, text="Book highlight")
        book = _make_export_book(
            user_book_id=2,
            title="Real Book",
            author="Real Author",
            category="books",
            highlights=[h2],
        )

        service = ReadwiseService(api_token="test_token")
        mock_client = MagicMock()
        mock_client.v2.export_highlights.return_value = iter([article, book])
        mock_client.close = MagicMock()

        with patch.object(service, "_create_client", return_value=mock_client):
            events = await _collect_events(service, db_session)

        complete = events[-1]
        assert complete.phase == "complete"
        # Only the book category should be processed as a real book
        assert complete.highlights_imported == 1

        result = await db_session.execute(select(Book))
        books = result.scalars().all()
        assert len(books) == 1
        assert books[0].title == "Real Book"


class TestSyncDownProgressEvents:
    """Tests for the shape and content of SyncDownProgress events."""

    async def test_processing_events_contain_book_title(self, db_session):
        """Each processing event message includes the book title being processed."""
        h1 = _make_export_highlight(id=701, text="Highlight A")
        book = _make_export_book(
            user_book_id=1,
            title="My Special Book",
            author="Author",
            highlights=[h1],
        )

        service = ReadwiseService(api_token="test_token")
        mock_client = MagicMock()
        mock_client.v2.export_highlights.return_value = iter([book])
        mock_client.close = MagicMock()

        with patch.object(service, "_create_client", return_value=mock_client):
            events = await _collect_events(service, db_session)

        processing_events = [e for e in events if e.phase == "processing"]
        assert len(processing_events) == 1
        assert "My Special Book" in processing_events[0].message

    async def test_fetching_events_per_book(self, db_session):
        """The streaming fetch yields fetching events as each book arrives."""
        h1 = _make_export_highlight(id=801, text="H1")
        h2 = _make_export_highlight(id=802, text="H2")
        book1 = _make_export_book(user_book_id=1, title="Book One", author="A", highlights=[h1])
        book2 = _make_export_book(user_book_id=2, title="Book Two", author="B", highlights=[h2])

        service = ReadwiseService(api_token="test_token")
        mock_client = MagicMock()
        mock_client.v2.export_highlights.return_value = iter([book1, book2])
        mock_client.close = MagicMock()

        with patch.object(service, "_create_client", return_value=mock_client):
            events = await _collect_events(service, db_session)

        fetching_events = [e for e in events if e.phase == "fetching"]
        # At least the initial "Fetching books from Readwise..." plus per-book fetching events
        assert len(fetching_events) >= 2

    async def test_processing_events_have_cumulative_counts(self, db_session):
        """Processing events show cumulative counts as books are processed."""
        h1 = _make_export_highlight(id=901, text="H1")
        h2 = _make_export_highlight(id=902, text="H2")
        book1 = _make_export_book(user_book_id=1, title="Book One", author="A", highlights=[h1])
        book2 = _make_export_book(user_book_id=2, title="Book Two", author="B", highlights=[h2])

        service = ReadwiseService(api_token="test_token")
        mock_client = MagicMock()
        mock_client.v2.export_highlights.return_value = iter([book1, book2])
        mock_client.close = MagicMock()

        with patch.object(service, "_create_client", return_value=mock_client):
            events = await _collect_events(service, db_session)

        processing_events = [e for e in events if e.phase == "processing"]
        assert len(processing_events) == 2

        # First processing event: 1 book, 1 highlight
        assert processing_events[0].books_processed == 1
        assert processing_events[0].highlights_imported == 1
        assert processing_events[0].books_total == 2

        # Second processing event: 2 books, 2 highlights
        assert processing_events[1].books_processed == 2
        assert processing_events[1].highlights_imported == 2
        assert processing_events[1].books_total == 2


class TestFetchBooks:
    """Tests for ReadwiseService.fetch_books() in isolation."""

    async def test_fetch_books_unconfigured_returns_empty(self):
        """fetch_books with no token returns an empty list."""
        mock_settings = MagicMock()
        mock_settings.readwise_api_token = None
        with patch("app.services.readwise.get_settings", return_value=mock_settings):
            service = ReadwiseService(api_token=None)

        result = await service.fetch_books()
        assert result == []

    async def test_fetch_books_maps_fields_correctly(self):
        """fetch_books correctly maps ExportBook fields to ReadwiseBook dataclass."""
        h1 = _make_export_highlight(
            id=1001,
            text="Highlight text",
            note="My note",
            location=55,
            highlighted_at=datetime(2024, 3, 1, tzinfo=UTC),
        )
        export_book = _make_export_book(
            user_book_id=100,
            title="Test Title",
            author="Test Author",
            cover_image_url="https://example.com/cover.jpg",
            highlights=[h1],
        )

        service = ReadwiseService(api_token="test_token")
        mock_client = MagicMock()
        mock_client.v2.export_highlights.return_value = iter([export_book])
        mock_client.close = MagicMock()

        with patch.object(service, "_create_client", return_value=mock_client):
            books = await service.fetch_books()

        assert len(books) == 1
        book = books[0]
        assert isinstance(book, ReadwiseBook)
        assert book.id == "100"
        assert book.title == "Test Title"
        assert book.author == "Test Author"
        assert book.cover_url == "https://example.com/cover.jpg"
        assert book.category == "books"

        assert len(book.highlights) == 1
        hl = book.highlights[0]
        assert isinstance(hl, ReadwiseHighlight)
        assert hl.id == "1001"
        assert hl.text == "Highlight text"
        assert hl.note == "My note"
        assert hl.location == 55
        assert hl.highlighted_at == datetime(2024, 3, 1, tzinfo=UTC)

    async def test_fetch_books_handles_none_fields(self):
        """fetch_books handles None title/author gracefully with defaults."""
        export_book = _make_export_book(
            user_book_id=200,
            title=None,
            author=None,
            highlights=[_make_export_highlight(id=1101, text="Some text")],
        )
        # Override the mock to return None
        export_book.title = None
        export_book.author = None
        export_book.category = "books"

        service = ReadwiseService(api_token="test_token")
        mock_client = MagicMock()
        mock_client.v2.export_highlights.return_value = iter([export_book])
        mock_client.close = MagicMock()

        with patch.object(service, "_create_client", return_value=mock_client):
            books = await service.fetch_books()

        assert len(books) == 1
        assert books[0].title == "Unknown Title"
        assert books[0].author == "Unknown Author"

    async def test_fetch_books_filters_non_books(self):
        """fetch_books only returns items with category 'books'."""
        article = _make_export_book(
            user_book_id=1,
            title="Article",
            author="Writer",
            category="articles",
            highlights=[_make_export_highlight(id=1201, text="Article hl")],
        )
        book = _make_export_book(
            user_book_id=2,
            title="Book",
            author="Author",
            category="books",
            highlights=[_make_export_highlight(id=1202, text="Book hl")],
        )

        service = ReadwiseService(api_token="test_token")
        mock_client = MagicMock()
        mock_client.v2.export_highlights.return_value = iter([article, book])
        mock_client.close = MagicMock()

        with patch.object(service, "_create_client", return_value=mock_client):
            result = await service.fetch_books()

        assert len(result) == 1
        assert result[0].title == "Book"


class TestPaginateCursorMonkeyPatch:
    """Tests for the monkey-patched ReadwiseClient.paginate that handles integer cursors.

    The Readwise API returns integer nextPageCursor values, but the original SDK
    code calls .startswith("http") on the cursor, crashing with AttributeError.
    Our monkey-patch converts the cursor to a string first.
    """

    def test_integer_cursor_does_not_crash(self):
        """paginate() handles integer nextPageCursor without AttributeError."""
        from app.services.readwise import _patched_paginate

        mock_client = Mock()
        # Page 1 returns data with an integer cursor
        page1_response = Mock()
        page1_response.json.return_value = {
            "results": [{"id": 1, "title": "Book 1"}],
            "nextPageCursor": 12345,  # integer, not string!
        }
        # Page 2 returns data with no cursor (end of pagination)
        page2_response = Mock()
        page2_response.json.return_value = {
            "results": [{"id": 2, "title": "Book 2"}],
            "nextPageCursor": None,
        }
        mock_client.get = Mock(side_effect=[page1_response, page2_response])

        results = list(
            _patched_paginate(
                mock_client,
                "https://readwise.io/api/v2/export/",
                params={},
                cursor_key="nextPageCursor",
            )
        )

        assert len(results) == 2
        assert results[0]["title"] == "Book 1"
        assert results[1]["title"] == "Book 2"
        # Verify pageCursor was passed as string on second request
        second_call_params = mock_client.get.call_args_list[1][1].get(
            "params",
            mock_client.get.call_args_list[1][0][1]
            if len(mock_client.get.call_args_list[1][0]) > 1
            else {},
        )
        assert second_call_params.get("pageCursor") == "12345"

    def test_string_url_cursor_still_works(self):
        """paginate() still handles full URL cursors correctly."""
        from app.services.readwise import _patched_paginate

        mock_client = Mock()
        page1_response = Mock()
        page1_response.json.return_value = {
            "results": [{"id": 1}],
            "next": "https://readwise.io/api/v2/books/?page=2&token=abc",
        }
        page2_response = Mock()
        page2_response.json.return_value = {
            "results": [{"id": 2}],
            "next": None,
        }
        mock_client.get = Mock(side_effect=[page1_response, page2_response])

        results = list(_patched_paginate(mock_client, "https://readwise.io/api/v2/books/"))
        assert len(results) == 2

    def test_none_cursor_stops_pagination(self):
        """paginate() stops when cursor is None."""
        from app.services.readwise import _patched_paginate

        mock_client = Mock()
        response = Mock()
        response.json.return_value = {
            "results": [{"id": 1}],
            "next": None,
        }
        mock_client.get = Mock(return_value=response)

        results = list(_patched_paginate(mock_client, "https://example.com/api/"))
        assert len(results) == 1
        assert mock_client.get.call_count == 1


class TestSyncDownFetchErrorMidStream:
    """Tests for errors that occur partway through fetching books."""

    async def test_error_after_partial_fetch_reports_failure(self, db_session):
        """If the SDK raises after yielding some books, sync_down yields an error event."""
        h1 = _make_export_highlight(id=1301, text="Good highlight")
        good_book = _make_export_book(
            user_book_id=1, title="Good Book", author="Author", highlights=[h1]
        )

        def _exploding_iterator():
            yield good_book
            raise ConnectionError("Connection reset after first page")

        service = ReadwiseService(api_token="test_token")
        mock_client = MagicMock()
        mock_client.v2.export_highlights.return_value = _exploding_iterator()
        mock_client.close = MagicMock()

        with patch.object(service, "_create_client", return_value=mock_client):
            events = await _collect_events(service, db_session)

        # Should have fetching events for the good book, then an error complete event
        complete = events[-1]
        assert complete.phase == "complete"
        assert len(complete.errors) > 0
        assert (
            "fetch" in " ".join(complete.errors).lower()
            or "connection" in " ".join(complete.errors).lower()
        )
