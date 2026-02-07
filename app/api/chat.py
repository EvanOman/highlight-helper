"""API endpoints and views for chat functionality."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.core.config import get_settings
from app.repositories.book import BookRepository, get_book_repo
from app.repositories.highlight import HighlightRepository, get_highlight_repo
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


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(
    request: Request,
    book_repo: BookRepository = Depends(get_book_repo),
    highlight_repo: HighlightRepository = Depends(get_highlight_repo),
):
    """Global chat page for all highlights."""
    book_count = await book_repo.get_total_count()
    highlight_count = await highlight_repo.get_total_count()

    return templates.TemplateResponse(
        request,
        "chat.html",
        {
            "book": None,
            "book_count": book_count,
            "highlight_count": highlight_count,
        },
    )


@router.get("/books/{book_id}/chat", response_class=HTMLResponse)
async def book_chat_page(
    request: Request,
    book_id: int,
    book_repo: BookRepository = Depends(get_book_repo),
):
    """Book-specific chat page."""
    book = await book_repo.get_or_404(book_id)
    highlight_count = await book_repo.get_highlight_count(book_id)

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
