"""Home page view."""

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse

from app.repositories.book import BookRepository, get_book_repo

from ._common import router, templates


@router.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    book_repo: BookRepository = Depends(get_book_repo),
):
    """Home page showing all books."""
    rows = await book_repo.list_with_highlight_counts()

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
        {"books": books},
    )
