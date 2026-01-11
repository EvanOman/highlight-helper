"""Pytest configuration and fixtures."""

import asyncio
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base, get_db
from app.main import app
from app.services.book_lookup import BookLookupService, get_book_lookup_service
from app.services.highlight_extractor import (
    ExtractedHighlight,
    HighlightExtractorService,
    get_highlight_extractor_service,
)
from app.services.isbn_extractor import (
    ExtractedISBN,
    ISBNExtractorService,
    get_isbn_extractor_service,
)
from app.services.readwise import (
    ReadwiseBatchResult,
    ReadwiseService,
    ReadwiseSyncResult,
    get_readwise_service,
)

# Use an in-memory SQLite database for testing
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def test_engine():
    """Create a test database engine."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def test_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session."""
    async_session = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with async_session() as session:
        yield session


@pytest.fixture
async def override_get_db(test_session: AsyncSession):
    """Override the get_db dependency for testing."""

    async def _override_get_db():
        yield test_session

    return _override_get_db


@pytest.fixture
def mock_book_lookup_service():
    """Create a mock book lookup service."""
    service = MagicMock(spec=BookLookupService)
    service.search_books = AsyncMock(return_value=[])
    service.search_by_isbn = AsyncMock(return_value=None)
    return service


@pytest.fixture
def mock_highlight_extractor_service():
    """Create a mock highlight extractor service."""
    service = MagicMock(spec=HighlightExtractorService)
    service.extract_highlight = AsyncMock(
        return_value=ExtractedHighlight(
            text="This is an extracted highlight.",
            confidence="high",
            page_number="42",
        )
    )
    return service


@pytest.fixture
def mock_isbn_extractor_service():
    """Create a mock ISBN extractor service."""
    service = MagicMock(spec=ISBNExtractorService)
    service.extract_isbn = AsyncMock(
        return_value=ExtractedISBN(
            isbn="9781234567890",
            confidence="high",
            source="barcode",
        )
    )
    return service


@pytest.fixture
def mock_readwise_service():
    """Create a mock Readwise service."""
    service = MagicMock(spec=ReadwiseService)
    service.is_configured = True
    service.validate_token = AsyncMock(return_value=True)
    service.send_highlight = AsyncMock(
        return_value=ReadwiseSyncResult(
            success=True,
            readwise_id="12345",
        )
    )
    service.send_highlights = AsyncMock(
        return_value=ReadwiseBatchResult(
            total=1,
            synced=1,
            failed=0,
            results=[ReadwiseSyncResult(success=True, readwise_id="12345")],
        )
    )
    return service


@pytest.fixture
def mock_readwise_service_unconfigured():
    """Create a mock Readwise service that is not configured."""
    service = MagicMock(spec=ReadwiseService)
    service.is_configured = False
    service.validate_token = AsyncMock(return_value=False)
    return service


@pytest.fixture
async def client(
    override_get_db,
    mock_book_lookup_service,
    mock_highlight_extractor_service,
    mock_isbn_extractor_service,
    mock_readwise_service,
) -> AsyncGenerator[AsyncClient, None]:
    """Create an async test client."""
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_book_lookup_service] = lambda: mock_book_lookup_service
    app.dependency_overrides[get_highlight_extractor_service] = (
        lambda: mock_highlight_extractor_service
    )
    app.dependency_overrides[get_isbn_extractor_service] = lambda: mock_isbn_extractor_service
    app.dependency_overrides[get_readwise_service] = lambda: mock_readwise_service

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def client_readwise_unconfigured(
    override_get_db,
    mock_book_lookup_service,
    mock_highlight_extractor_service,
    mock_isbn_extractor_service,
    mock_readwise_service_unconfigured,
) -> AsyncGenerator[AsyncClient, None]:
    """Create an async test client with Readwise not configured."""
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_book_lookup_service] = lambda: mock_book_lookup_service
    app.dependency_overrides[get_highlight_extractor_service] = (
        lambda: mock_highlight_extractor_service
    )
    app.dependency_overrides[get_isbn_extractor_service] = lambda: mock_isbn_extractor_service
    app.dependency_overrides[get_readwise_service] = lambda: mock_readwise_service_unconfigured

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def sample_book(test_session: AsyncSession):
    """Create a sample book for testing."""
    from app.models.book import Book

    book = Book(
        title="Test Book",
        author="Test Author",
        isbn="1234567890",
        cover_url="https://example.com/cover.jpg",
    )
    test_session.add(book)
    await test_session.flush()
    await test_session.refresh(book)
    return book


@pytest.fixture
async def sample_highlight(test_session: AsyncSession, sample_book):
    """Create a sample highlight for testing."""
    from app.models.highlight import Highlight

    highlight = Highlight(
        book_id=sample_book.id,
        text="This is a test highlight.",
        note="Test note",
        page_number="42",
    )
    test_session.add(highlight)
    await test_session.flush()
    await test_session.refresh(highlight)
    return highlight


@pytest.fixture
async def synced_highlight(test_session: AsyncSession, sample_book):
    """Create a sample highlight that has been synced to Readwise."""
    from datetime import datetime, timezone

    from app.models.highlight import Highlight

    highlight = Highlight(
        book_id=sample_book.id,
        text="This is a synced highlight.",
        note="Synced note",
        page_number="100",
        readwise_id="12345",
        synced_at=datetime.now(tz=timezone.utc),
    )
    test_session.add(highlight)
    await test_session.flush()
    await test_session.refresh(highlight)
    return highlight
