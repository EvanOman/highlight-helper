"""Capture entry view."""

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse

from app.repositories.book import BookRepository, get_book_repo

from ._common import router, templates


@router.get("/capture", response_class=HTMLResponse)
async def capture_page(
    request: Request,
    book_repo: BookRepository = Depends(get_book_repo),
):
    """Camera-first entry point for extracting a highlight."""
    rows = await book_repo.list_with_highlight_counts()
    books = [
        {
            "id": book.id,
            "title": book.title,
            "author": book.author,
            "cover_url": book.cover_url,
            "is_starred": book.is_starred,
            "highlight_count": highlight_count,
        }
        for book, highlight_count in rows
    ]

    return templates.TemplateResponse(
        request,
        "capture.html",
        {"books": books, "first_book": books[0] if books else None},
    )
