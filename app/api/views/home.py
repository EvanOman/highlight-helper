"""Home page view."""

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.book import Book
from app.models.highlight import Highlight

from ._common import router, templates


@router.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Home page showing all books."""
    # Get books with highlight counts
    highlight_count_subq = (
        select(Highlight.book_id, func.count(Highlight.id).label("count"))
        .group_by(Highlight.book_id)
        .subquery()
    )

    query = (
        select(Book, func.coalesce(highlight_count_subq.c.count, 0).label("highlight_count"))
        .outerjoin(highlight_count_subq, Book.id == highlight_count_subq.c.book_id)
        .order_by(Book.created_at.desc())
    )

    result = await db.execute(query)
    rows = result.all()

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
