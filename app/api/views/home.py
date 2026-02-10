"""Home page view."""

from fastapi import Depends, Query, Request
from fastapi.responses import HTMLResponse

from app.repositories.book import BookRepository, get_book_repo

from ._common import router, templates


@router.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    page: int = Query(1, ge=1),
    book_repo: BookRepository = Depends(get_book_repo),
):
    """Home page showing all books."""
    per_page = 24
    total = await book_repo.get_total_count()
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)

    rows = await book_repo.list_with_highlight_counts(skip=(page - 1) * per_page, limit=per_page)

    books = [
        {
            "id": book.id,
            "title": book.title,
            "author": book.author,
            "cover_url": book.cover_url,
            "highlight_count": highlight_count,
        }
        for book, highlight_count in rows
    ]

    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "books": books,
            "current_page": page,
            "total_pages": total_pages,
            "total_books": total,
            "page_path": "/",
        },
    )
