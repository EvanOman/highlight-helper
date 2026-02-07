"""Book API routes."""

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.schemas import (
    BookCreate,
    BookListResponse,
    BookResponse,
    BookSearchResponse,
    BookSearchResult,
    BookUpdate,
)
from app.repositories.book import BookRepository, get_book_repo
from app.services.book_lookup import BookLookupService, get_book_lookup_service

router = APIRouter(prefix="/api/books", tags=["books"])


@router.get("", response_model=BookListResponse)
async def list_books(
    skip: int = 0,
    limit: int = 50,
    book_repo: BookRepository = Depends(get_book_repo),
) -> BookListResponse:
    """List all books with their highlight counts."""
    rows = await book_repo.list_with_highlight_counts(skip=skip, limit=limit)

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

    total = await book_repo.get_total_count()

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
    book_repo: BookRepository = Depends(get_book_repo),
) -> BookResponse:
    """Create a new book."""
    book = await book_repo.create(
        title=book_data.title,
        author=book_data.author,
        isbn=book_data.isbn,
        cover_url=book_data.cover_url,
    )

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
    book_repo: BookRepository = Depends(get_book_repo),
) -> BookResponse:
    """Get a specific book by ID."""
    book = await book_repo.get_or_raise(book_id)
    highlight_count = await book_repo.get_highlight_count(book_id)

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
    book_repo: BookRepository = Depends(get_book_repo),
) -> BookResponse:
    """Update a book."""
    book = await book_repo.get_or_raise(book_id)

    update_data = book_data.model_dump(exclude_unset=True)
    book = await book_repo.update(book, **update_data)

    highlight_count = await book_repo.get_highlight_count(book_id)

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
    book_repo: BookRepository = Depends(get_book_repo),
) -> None:
    """Delete a book and all its highlights."""
    book = await book_repo.get_or_raise(book_id)
    await book_repo.delete(book)
