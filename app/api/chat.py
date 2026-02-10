"""API endpoints and views for chat functionality."""

import logging
from typing import cast

from anthropic.types import MessageParam
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.views._common import templates
from app.core.database import get_async_session, get_db
from app.repositories.book import BookRepository, get_book_repo
from app.repositories.chat import ChatRepository, get_chat_repo
from app.repositories.highlight import HighlightRepository, get_highlight_repo
from app.services.chat import ChatService, get_chat_service
from app.services.settings import SettingsService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


class ChatMessageRequest(BaseModel):
    """Request model for chat messages."""

    message: str
    book_id: int | None = None
    thread_id: int | None = None


class CreateThreadRequest(BaseModel):
    """Request model for creating a thread."""

    title: str
    book_id: int | None = None


# View endpoints for HTML pages


CHAT_MODELS = [
    ("claude-opus-4-6", "Claude Opus 4.6"),
    ("claude-sonnet-4-5-20250929", "Claude Sonnet 4.5"),
    ("claude-haiku-4-5-20251001", "Claude Haiku 4.5"),
]


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(
    request: Request,
    book_repo: BookRepository = Depends(get_book_repo),
    highlight_repo: HighlightRepository = Depends(get_highlight_repo),
    chat_repo: ChatRepository = Depends(get_chat_repo),
    db: AsyncSession = Depends(get_db),
):
    """Global chat page for all highlights."""
    book_count = await book_repo.get_total_count()
    highlight_count = await highlight_repo.get_total_count()
    threads = await chat_repo.list_threads(book_id=None)
    settings_svc = SettingsService(db)
    chat_model = await settings_svc.get_chat_model()

    return templates.TemplateResponse(
        request,
        "chat.html",
        {
            "book": None,
            "book_count": book_count,
            "highlight_count": highlight_count,
            "threads": threads,
            "chat_model": chat_model,
            "chat_models": CHAT_MODELS,
        },
    )


@router.get("/books/{book_id}/chat", response_class=HTMLResponse)
async def book_chat_page(
    request: Request,
    book_id: int,
    book_repo: BookRepository = Depends(get_book_repo),
    chat_repo: ChatRepository = Depends(get_chat_repo),
    db: AsyncSession = Depends(get_db),
):
    """Book-specific chat page."""
    book = await book_repo.get_or_raise(book_id)
    highlight_count = await book_repo.get_highlight_count(book_id)
    threads = await chat_repo.list_threads(book_id=book_id)
    settings_svc = SettingsService(db)
    chat_model = await settings_svc.get_chat_model()

    return templates.TemplateResponse(
        request,
        "chat.html",
        {
            "book": book,
            "book_count": None,
            "highlight_count": highlight_count,
            "threads": threads,
            "chat_model": chat_model,
            "chat_models": CHAT_MODELS,
        },
    )


# Book search endpoint


@router.get("/api/chat/books")
async def search_books_for_chat(
    q: str = "",
    book_repo: BookRepository = Depends(get_book_repo),
):
    """Search local books by title/author for chat scope selection.

    Returns up to 10 results with highlight counts. If q is empty,
    returns the 10 most recent books.
    """
    results = await book_repo.search_with_highlight_counts(query=q, limit=10)
    return {
        "books": [
            {
                "id": book.id,
                "title": book.title,
                "author": book.author,
                "highlight_count": count,
            }
            for book, count in results
        ]
    }


# Thread CRUD endpoints


@router.get("/api/chat/threads")
async def list_threads(
    book_id: int | None = None,
    chat_repo: ChatRepository = Depends(get_chat_repo),
):
    """List chat threads, optionally filtered by book_id."""
    threads = await chat_repo.list_threads(book_id=book_id)
    return [
        {
            "id": t.id,
            "title": t.title,
            "book_id": t.book_id,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        }
        for t in threads
    ]


@router.post("/api/chat/threads")
async def create_thread(
    request: CreateThreadRequest,
    chat_repo: ChatRepository = Depends(get_chat_repo),
    book_repo: BookRepository = Depends(get_book_repo),
):
    """Create a new chat thread."""
    if request.book_id is not None:
        await book_repo.get_or_raise(request.book_id)
    thread = await chat_repo.create_thread(title=request.title, book_id=request.book_id)
    return {
        "id": thread.id,
        "title": thread.title,
        "book_id": thread.book_id,
        "created_at": thread.created_at.isoformat() if thread.created_at else None,
        "updated_at": thread.updated_at.isoformat() if thread.updated_at else None,
    }


@router.get("/api/chat/threads/{thread_id}/messages")
async def get_thread_messages(
    thread_id: int,
    chat_repo: ChatRepository = Depends(get_chat_repo),
):
    """Get all messages for a thread."""
    await chat_repo.get_thread_or_raise(thread_id)
    messages = await chat_repo.list_messages(thread_id)
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in messages
    ]


@router.delete("/api/chat/threads/{thread_id}")
async def delete_thread(
    thread_id: int,
    chat_repo: ChatRepository = Depends(get_chat_repo),
):
    """Delete a chat thread and all its messages."""
    thread = await chat_repo.get_thread_or_raise(thread_id)
    await chat_repo.delete_thread(thread)
    return {"ok": True}


# Message endpoint


@router.post("/api/chat/message")
async def send_chat_message(
    request: ChatMessageRequest,
    chat_service: ChatService = Depends(get_chat_service),
    chat_repo: ChatRepository = Depends(get_chat_repo),
    book_repo: BookRepository = Depends(get_book_repo),
):
    """Send a message and get a streaming response.

    The response is streamed using Server-Sent Events (SSE) format.
    The user message is persisted before streaming begins. The assistant
    response is persisted after the stream completes using an independent
    database session.
    """
    thread_id = request.thread_id

    # Create thread if needed
    if thread_id is None:
        if request.book_id is not None:
            await book_repo.get_or_raise(request.book_id)
        title = request.message[:50]
        thread = await chat_repo.create_thread(title=title, book_id=request.book_id)
        thread_id = thread.id
    else:
        await chat_repo.get_thread_or_raise(thread_id)
        await chat_repo.update_thread_timestamp(thread_id)

    # Save user message immediately
    await chat_repo.create_message(thread_id=thread_id, role="user", content=request.message)

    # Load full conversation history from DB
    messages = await chat_repo.list_messages(thread_id)
    history = cast(
        list[MessageParam],
        [{"role": m.role, "content": m.content} for m in messages],
    )

    # Commit the request session now to release the SQLite lock.
    # The streaming generator uses an independent session (get_async_session)
    # to save the assistant response, which would deadlock if this session
    # still holds a write lock.
    await chat_repo.db.commit()

    async def generate():
        full_response = ""
        async for chunk in chat_service.send_message_from_history(
            history=history,
            book_id=request.book_id,
        ):
            full_response += chunk
            for line in chunk.split("\n"):
                yield f"data: {line}\n"
            yield "\n"

        # Save assistant response and metrics using independent session
        try:
            async with get_async_session() as session:
                from app.repositories.chat import ChatRepository as ChatRepo
                from app.repositories.chat_metric import ChatMetricRepository

                repo = ChatRepo(session)
                await repo.create_message(
                    thread_id=thread_id, role="assistant", content=full_response
                )
                await repo.update_thread_timestamp(thread_id)

                if chat_service.last_metrics:
                    metric_repo = ChatMetricRepository(session)
                    await metric_repo.create(
                        thread_id=thread_id,
                        book_id=request.book_id,
                        message_count=len(history),
                        **chat_service.last_metrics,
                    )
        except Exception:
            logger.exception("Failed to save assistant message for thread %s", thread_id)
            yield "event: error\ndata: Failed to save response\n\n"

        # Signal completion with thread_id
        yield f"event: done\ndata: {thread_id}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
