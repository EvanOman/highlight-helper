"""Book API routes."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    BookCreate,
    BookListResponse,
    BookResponse,
    BookSearchResponse,
    BookSearchResult,
    BookUpdate,
)
from app.core.database import get_db
from app.models.book import Book
from app.models.highlight import Highlight
from app.services.book_lookup import BookLookupService, get_book_lookup_service

router = APIRouter(prefix="/api/books", tags=["books"])


@router.get("", response_model=BookListResponse)
async def list_books(
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> BookListResponse:
    """List all books with their highlight counts."""
    # Get books with highlight counts using a subquery
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
        .limit(limit)
    )

    result = await db.execute(query)
    rows = result.all()

    books = [
        BookResponse(
            id=book.id,
            title=book.title,
            author=book.author,
            isbn=book.isbn,
            cover_url=book.cover_url,
            created_at=book.created_at,
            highlight_count=highlight_count,
        )
        for book, highlight_count in rows
    ]

    # Get total count
    total_query = select(func.count(Book.id))
    total_result = await db.execute(total_query)
    total = total_result.scalar() or 0

    return BookListResponse(books=books, total=total)


@router.get("/search", response_model=BookSearchResponse)
async def search_books(
    q: str,
    book_lookup: BookLookupService = Depends(get_book_lookup_service),
) -> BookSearchResponse:
    """Search for books using Google Books API."""
    if not q or len(q) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Search query must be at least 2 characters",
        )

    results = await book_lookup.search_books(q)

    return BookSearchResponse(
        results=[
            BookSearchResult(
                title=book.title,
                author=book.author,
                isbn=book.isbn,
                cover_url=book.cover_url,
                description=book.description,
            )
            for book in results
        ]
    )


@router.post("", response_model=BookResponse, status_code=status.HTTP_201_CREATED)
async def create_book(
    book_data: BookCreate,
    db: AsyncSession = Depends(get_db),
) -> BookResponse:
    """Create a new book."""
    book = Book(
        title=book_data.title,
        author=book_data.author,
        isbn=book_data.isbn,
        cover_url=book_data.cover_url,
    )
    db.add(book)
    await db.flush()
    await db.refresh(book)

    return BookResponse(
        id=book.id,
        title=book.title,
        author=book.author,
        isbn=book.isbn,
        cover_url=book.cover_url,
        created_at=book.created_at,
        highlight_count=0,
    )


@router.get("/{book_id}", response_model=BookResponse)
async def get_book(
    book_id: int,
    db: AsyncSession = Depends(get_db),
) -> BookResponse:
    """Get a specific book by ID."""
    query = select(Book).where(Book.id == book_id)
    result = await db.execute(query)
    book = result.scalar_one_or_none()

    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )

    # Get highlight count
    count_query = select(func.count(Highlight.id)).where(Highlight.book_id == book_id)
    count_result = await db.execute(count_query)
    highlight_count = count_result.scalar() or 0

    return BookResponse(
        id=book.id,
        title=book.title,
        author=book.author,
        isbn=book.isbn,
        cover_url=book.cover_url,
        created_at=book.created_at,
        highlight_count=highlight_count,
    )


@router.patch("/{book_id}", response_model=BookResponse)
async def update_book(
    book_id: int,
    book_data: BookUpdate,
    db: AsyncSession = Depends(get_db),
) -> BookResponse:
    """Update a book."""
    query = select(Book).where(Book.id == book_id)
    result = await db.execute(query)
    book = result.scalar_one_or_none()

    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )

    update_data = book_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(book, field, value)

    await db.flush()
    await db.refresh(book)

    # Get highlight count
    count_query = select(func.count(Highlight.id)).where(Highlight.book_id == book_id)
    count_result = await db.execute(count_query)
    highlight_count = count_result.scalar() or 0

    return BookResponse(
        id=book.id,
        title=book.title,
        author=book.author,
        isbn=book.isbn,
        cover_url=book.cover_url,
        created_at=book.created_at,
        highlight_count=highlight_count,
    )


@router.delete("/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_book(
    book_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a book and all its highlights."""
    query = select(Book).where(Book.id == book_id)
    result = await db.execute(query)
    book = result.scalar_one_or_none()

    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )

    await db.delete(book)
