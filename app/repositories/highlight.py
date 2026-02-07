"""Highlight repository for database access."""

from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.models.book import Book
from app.models.highlight import AnnotationType, Highlight


class HighlightRepository:
    """Repository for Highlight database operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, highlight_id: int) -> Highlight | None:
        """Get a highlight by ID, or None if not found."""
        query = select(Highlight).where(Highlight.id == highlight_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_or_404(self, highlight_id: int) -> Highlight:
        """Get a highlight by ID, raising HTTP 404 if not found."""
        highlight = await self.get_by_id(highlight_id)
        if not highlight:
            raise NotFoundError("Highlight not found")
        return highlight

    async def get_with_book_or_404(
        self, highlight_id: int, book_id: int | None = None
    ) -> tuple[Highlight, Book]:
        """Get a highlight with its book, raising HTTP 404 if not found.

        Args:
            highlight_id: The highlight ID to look up.
            book_id: If provided, also verifies the highlight belongs to this book.
        """
        if book_id is not None:
            query = select(Highlight).where(
                Highlight.id == highlight_id, Highlight.book_id == book_id
            )
        else:
            query = select(Highlight, Book).join(Book).where(Highlight.id == highlight_id)

        result = await self.db.execute(query)

        if book_id is not None:
            highlight = result.scalar_one_or_none()
            if not highlight:
                raise NotFoundError("Highlight not found")
            # Need to fetch the book separately since we queried just the highlight
            from app.repositories.book import BookRepository

            book_repo = BookRepository(self.db)
            book = await book_repo.get_or_404(book_id)
            return highlight, book
        else:
            row = result.first()
            if not row:
                raise NotFoundError("Highlight not found")
            return row[0], row[1]

    async def list_for_book(self, book_id: int) -> list[Highlight]:
        """List all highlights for a book, ordered by creation date descending."""
        query = (
            select(Highlight)
            .where(Highlight.book_id == book_id)
            .order_by(Highlight.created_at.desc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_all_with_books(
        self, skip: int = 0, limit: int | None = None
    ) -> list[tuple[Highlight, Book]]:
        """List all highlights with their books, ordered by creation date descending."""
        query = (
            select(Highlight, Book).join(Book).order_by(Highlight.created_at.desc()).offset(skip)
        )
        if limit is not None:
            query = query.limit(limit)
        result = await self.db.execute(query)
        return [(row[0], row[1]) for row in result.all()]

    async def list_unsynced(
        self,
        book_id: int | None = None,
        exclude_notes: bool = True,
    ) -> list[tuple[Highlight, Book]]:
        """List unsynced highlights with their books.

        Args:
            book_id: If provided, only return highlights for this book.
            exclude_notes: If True (default), exclude NOTE type highlights.
        """
        query = select(Highlight, Book).join(Book).where(Highlight.synced_at.is_(None))
        if book_id is not None:
            query = query.where(Highlight.book_id == book_id)
        if exclude_notes:
            query = query.where(Highlight.type == AnnotationType.HIGHLIGHT)
        result = await self.db.execute(query)
        return [(row[0], row[1]) for row in result.all()]

    async def count_unsynced_notes(self, book_id: int | None = None) -> int:
        """Count unsynced notes (for logging purposes)."""
        query = (
            select(func.count(Highlight.id))
            .where(Highlight.synced_at.is_(None))
            .where(Highlight.type == AnnotationType.NOTE)
        )
        if book_id is not None:
            query = query.where(Highlight.book_id == book_id)
        result = await self.db.execute(query)
        return result.scalar() or 0

    async def get_total_count(self) -> int:
        """Get total number of highlights."""
        query = select(func.count(Highlight.id))
        result = await self.db.execute(query)
        return result.scalar() or 0

    async def create(self, **kwargs) -> Highlight:
        """Create a new highlight."""
        highlight = Highlight(**kwargs)
        self.db.add(highlight)
        await self.db.flush()
        await self.db.refresh(highlight)
        return highlight

    async def delete(self, highlight: Highlight) -> None:
        """Delete a highlight."""
        await self.db.delete(highlight)


async def get_highlight_repo(db: AsyncSession = Depends(get_db)) -> HighlightRepository:
    """FastAPI dependency that provides a HighlightRepository."""
    return HighlightRepository(db)
