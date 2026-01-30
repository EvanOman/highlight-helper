"""API endpoints and views for chat functionality."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.models.book import Book
from app.models.highlight import Highlight
from app.services.chat import ChatService, get_chat_service

router = APIRouter(tags=["chat"])

# Set up templates with base_path for subpath deployments
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()
templates.env.globals["base_path"] = settings.root_path


class ChatMessageRequest(BaseModel):
    """Request model for chat messages."""

    message: str
    book_id: int | None = None
    # Conversation history for multi-turn chat
    history: list[dict] | None = None


# View endpoints for HTML pages


@router.get("/chat/", response_class=HTMLResponse)
async def chat_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Global chat page for all highlights."""
    book_count = await db.scalar(select(func.count(Book.id)))
    highlight_count = await db.scalar(select(func.count(Highlight.id)))

    return templates.TemplateResponse(
        request,
        "chat.html",
        {
            "book": None,
            "book_count": book_count,
            "highlight_count": highlight_count,
        },
    )


@router.get("/books/{book_id}/chat/", response_class=HTMLResponse)
async def book_chat_page(
    request: Request,
    book_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Book-specific chat page."""
    query = select(Book).where(Book.id == book_id)
    result = await db.execute(query)
    book = result.scalar_one_or_none()

    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    highlight_count = await db.scalar(
        select(func.count(Highlight.id)).where(Highlight.book_id == book_id)
    )

    return templates.TemplateResponse(
        request,
        "chat.html",
        {
            "book": book,
            "book_count": None,
            "highlight_count": highlight_count,
        },
    )


# API endpoints


@router.post("/api/chat/message")
async def send_chat_message(
    request: ChatMessageRequest,
    chat_service: ChatService = Depends(get_chat_service),
):
    """Send a message and get a streaming response.

    The response is streamed using Server-Sent Events (SSE) format.
    """
    # Note: Book validation is done in the chat service when building context

    async def generate():
        async for chunk in chat_service.send_message(
            message=request.message,
            book_id=request.book_id,
            conversation_history=request.history,
        ):
            # SSE format: data: <content>\n\n
            yield f"data: {chunk}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable buffering in nginx
        },
    )
