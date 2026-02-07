"""Book repository for database access."""

from fastapi import Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.book import Book
from app.models.highlight import Highlight


class BookRepository:
    """Repository for Book database operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, book_id: int) -> Book | None:
        """Get a book by ID, or None if not found."""
        query = select(Book).where(Book.id == book_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_or_404(self, book_id: int) -> Book:
        """Get a book by ID, raising HTTP 404 if not found."""
        book = await self.get_by_id(book_id)
        if not book:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Book not found",
            )
        return book

    async def list_with_highlight_counts(
        self, skip: int = 0, limit: int | None = None
    ) -> list[tuple[Book, int]]:
        """List books with their highlight counts."""
        highlight_count_subq = (
            select(Highlight.book_id, func.count(Highlight.id).label("count"))
            .group_by(Highlight.book_id)
            .subquery()
        )

        query = (
            select(Book, func.coalesce(highlight_count_subq.c.count, 0).label("highlight_count"))
            .outerjoin(highlight_count_subq, Book.id == highlight_count_subq.c.book_id)
            .order_by(Book.created_at.desc())
            .offset(skip)
        )
        if limit is not None:
            query = query.limit(limit)

        result = await self.db.execute(query)
        return [(row[0], row[1]) for row in result.all()]

    async def get_highlight_count(self, book_id: int) -> int:
        """Get the highlight count for a book."""
        count_query = select(func.count(Highlight.id)).where(Highlight.book_id == book_id)
        count_result = await self.db.execute(count_query)
        return count_result.scalar() or 0

    async def get_total_count(self) -> int:
        """Get total number of books."""
        total_query = select(func.count(Book.id))
        total_result = await self.db.execute(total_query)
        return total_result.scalar() or 0

    async def create(self, **kwargs) -> Book:
        """Create a new book."""
        book = Book(**kwargs)
        self.db.add(book)
        await self.db.flush()
        await self.db.refresh(book)
        return book

    async def delete(self, book: Book) -> None:
        """Delete a book."""
        await self.db.delete(book)


async def get_book_repo(db: AsyncSession = Depends(get_db)) -> BookRepository:
    """FastAPI dependency that provides a BookRepository."""
    return BookRepository(db)
