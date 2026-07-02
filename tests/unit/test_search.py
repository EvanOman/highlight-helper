"""Unit tests for FTS5 search infrastructure and SearchRepository."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base, create_fts_and_indexes
from app.models.book import Book
from app.models.highlight import Highlight
from app.repositories.search import SearchRepository

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def fts_engine():
    """Create a test engine with FTS5 tables via migrations."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(create_fts_and_indexes)
    yield engine
    await engine.dispose()


@pytest.fixture
async def fts_session(fts_engine):
    """Create a session with FTS5 tables available."""
    maker = async_sessionmaker(fts_engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session


class TestFTS5Setup:
    """Tests that FTS5 virtual tables are created during init_db."""

    async def test_books_fts_table_exists(self, fts_session: AsyncSession):
        """Verify books_fts virtual table was created by migrations."""
        result = await fts_session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='books_fts'")
        )
        row = result.fetchone()
        assert row is not None, "books_fts table should exist"

    async def test_highlights_fts_table_exists(self, fts_session: AsyncSession):
        """Verify highlights_fts virtual table was created by migrations."""
        result = await fts_session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='highlights_fts'")
        )
        row = result.fetchone()
        assert row is not None, "highlights_fts table should exist"

    async def test_books_triggers_exist(self, fts_session: AsyncSession):
        """Verify sync triggers were created for books_fts."""
        result = await fts_session.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='trigger' "
                "AND name IN ('books_ai', 'books_ad', 'books_au')"
            )
        )
        names = {row[0] for row in result.fetchall()}
        assert names == {"books_ai", "books_ad", "books_au"}

    async def test_highlights_triggers_exist(self, fts_session: AsyncSession):
        """Verify sync triggers were created for highlights_fts."""
        result = await fts_session.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='trigger' "
                "AND name IN ('highlights_ai', 'highlights_ad', 'highlights_au')"
            )
        )
        names = {row[0] for row in result.fetchall()}
        assert names == {"highlights_ai", "highlights_ad", "highlights_au"}

    async def test_idempotent_fts_setup(self, fts_engine):
        """Running FTS setup twice should not error."""
        async with fts_engine.begin() as conn:
            # FTS already created in fixture; run again to test idempotence
            await conn.run_sync(create_fts_and_indexes)


class TestSearchBooks:
    """Tests for SearchRepository.search_books."""

    async def _seed_books(self, session: AsyncSession):
        """Insert a few books for search tests."""
        books = [
            Book(title="Atomic Habits", author="James Clear"),
            Book(title="Deep Work", author="Cal Newport"),
            Book(title="The Lean Startup", author="Eric Ries"),
        ]
        session.add_all(books)
        await session.flush()
        return books

    async def test_search_returns_matching_books(self, fts_session: AsyncSession):
        await self._seed_books(fts_session)
        await fts_session.commit()
        repo = SearchRepository(fts_session)
        results = await repo.search_books("Atomic")
        assert len(results) == 1
        assert results[0]["title"] == "Atomic Habits"

    async def test_search_by_author(self, fts_session: AsyncSession):
        await self._seed_books(fts_session)
        await fts_session.commit()
        repo = SearchRepository(fts_session)
        results = await repo.search_books("Newport")
        assert len(results) == 1
        assert results[0]["author"] == "Cal Newport"

    async def test_search_empty_query_returns_empty(self, fts_session: AsyncSession):
        await self._seed_books(fts_session)
        await fts_session.commit()
        repo = SearchRepository(fts_session)
        results = await repo.search_books("")
        assert results == []

    async def test_search_no_match_returns_empty(self, fts_session: AsyncSession):
        await self._seed_books(fts_session)
        await fts_session.commit()
        repo = SearchRepository(fts_session)
        results = await repo.search_books("Nonexistent Book XYZ")
        assert results == []

    async def test_search_respects_limit(self, fts_session: AsyncSession):
        # Add multiple books that match "Book"
        for i in range(5):
            fts_session.add(Book(title=f"Book Number {i}", author="Author"))
        await fts_session.flush()
        await fts_session.commit()
        repo = SearchRepository(fts_session)
        results = await repo.search_books("Book", limit=2)
        assert len(results) == 2

    async def test_search_result_has_expected_keys(self, fts_session: AsyncSession):
        await self._seed_books(fts_session)
        await fts_session.commit()
        repo = SearchRepository(fts_session)
        results = await repo.search_books("Habits")
        assert len(results) == 1
        result = results[0]
        assert "id" in result
        assert "title" in result
        assert "author" in result
        assert "rank" in result
        assert "snippet" in result


class TestSearchHighlights:
    """Tests for SearchRepository.search_highlights."""

    async def _seed_data(self, session: AsyncSession):
        """Insert books and highlights for search tests."""
        book = Book(title="Atomic Habits", author="James Clear")
        session.add(book)
        await session.flush()

        highlights = [
            Highlight(
                book_id=book.id,
                text="The quality of our lives depends on the quality of our habits.",
                note="Key theme",
            ),
            Highlight(
                book_id=book.id,
                text="Every action you take is a vote for the person you wish to become.",
                note=None,
            ),
            Highlight(
                book_id=book.id,
                text="You do not rise to the level of your goals.",
                note="Goals vs systems",
            ),
        ]
        session.add_all(highlights)
        await session.flush()
        return book, highlights

    async def test_search_highlights_by_text(self, fts_session: AsyncSession):
        await self._seed_data(fts_session)
        await fts_session.commit()
        repo = SearchRepository(fts_session)
        results = await repo.search_highlights("habits")
        assert len(results) >= 1
        assert any("habits" in (r["text"] or "").lower() for r in results)

    async def test_search_highlights_by_note(self, fts_session: AsyncSession):
        await self._seed_data(fts_session)
        await fts_session.commit()
        repo = SearchRepository(fts_session)
        results = await repo.search_highlights("goals systems")
        assert len(results) >= 1

    async def test_search_highlights_includes_book_info(self, fts_session: AsyncSession):
        await self._seed_data(fts_session)
        await fts_session.commit()
        repo = SearchRepository(fts_session)
        results = await repo.search_highlights("vote")
        assert len(results) == 1
        assert results[0]["book_title"] == "Atomic Habits"
        assert results[0]["book_author"] == "James Clear"

    async def test_search_highlights_empty_query(self, fts_session: AsyncSession):
        await self._seed_data(fts_session)
        await fts_session.commit()
        repo = SearchRepository(fts_session)
        results = await repo.search_highlights("")
        assert results == []

    async def test_search_highlights_result_keys(self, fts_session: AsyncSession):
        await self._seed_data(fts_session)
        await fts_session.commit()
        repo = SearchRepository(fts_session)
        results = await repo.search_highlights("quality")
        assert len(results) >= 1
        result = results[0]
        for key in (
            "id",
            "book_id",
            "text",
            "note",
            "book_title",
            "book_author",
            "rank",
            "snippet",
        ):
            assert key in result


class TestFTS5Triggers:
    """Tests that FTS5 triggers keep the index in sync."""

    async def test_new_data_is_searchable_after_insert(self, fts_session: AsyncSession):
        """Inserting a book should make it searchable via FTS."""
        repo = SearchRepository(fts_session)
        # Nothing yet
        assert await repo.search_books("Leadership") == []

        book = Book(title="Leaders Eat Last", author="Simon Sinek")
        fts_session.add(book)
        await fts_session.flush()
        await fts_session.commit()

        results = await repo.search_books("Leadership")
        # "Leadership" won't match "Leaders" exactly, but "Leaders" will
        results = await repo.search_books("Leaders")
        assert len(results) == 1
        assert results[0]["title"] == "Leaders Eat Last"

    async def test_deleted_book_not_searchable(self, fts_session: AsyncSession):
        """Deleting a book should remove it from FTS index."""
        book = Book(title="Temporary Book", author="Nobody")
        fts_session.add(book)
        await fts_session.flush()
        await fts_session.commit()

        repo = SearchRepository(fts_session)
        results = await repo.search_books("Temporary")
        assert len(results) == 1

        await fts_session.delete(book)
        await fts_session.flush()
        await fts_session.commit()

        results = await repo.search_books("Temporary")
        assert len(results) == 0

    async def test_updated_book_reflects_in_search(self, fts_session: AsyncSession):
        """Updating a book title should update the FTS index."""
        book = Book(title="Old Title", author="Author")
        fts_session.add(book)
        await fts_session.flush()
        await fts_session.commit()

        repo = SearchRepository(fts_session)
        assert len(await repo.search_books("Old")) == 1

        book.title = "New Title"
        await fts_session.flush()
        await fts_session.commit()

        assert len(await repo.search_books("Old")) == 0
        results = await repo.search_books("New")
        assert len(results) == 1
        assert results[0]["title"] == "New Title"

    async def test_highlight_trigger_insert(self, fts_session: AsyncSession):
        """Inserting a highlight should make it searchable."""
        book = Book(title="Test Book", author="Author")
        fts_session.add(book)
        await fts_session.flush()

        highlight = Highlight(
            book_id=book.id,
            text="Innovation distinguishes between a leader and a follower.",
            note="Steve Jobs quote",
        )
        fts_session.add(highlight)
        await fts_session.flush()
        await fts_session.commit()

        repo = SearchRepository(fts_session)
        results = await repo.search_highlights("innovation")
        assert len(results) == 1
        assert "innovation" in results[0]["text"].lower()
