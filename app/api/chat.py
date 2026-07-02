"""API endpoints and views for chat functionality."""

import json
import logging
from typing import Any, cast

from chatkit import ChatEvent, ChatEventType, ChatRequest, stream_chat_events
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette import EventSourceResponse

from app.api.views._common import templates
from app.core.database import get_async_session, get_db
from app.core.model_registry import CHAT_MODEL_CHOICES
from app.repositories.book import BookRepository, get_book_repo
from app.repositories.chat import ChatRepository, get_chat_repo
from app.repositories.coaching import CoachingRepository
from app.repositories.highlight import HighlightRepository, get_highlight_repo
from app.services.chat import ChatService, get_chat_service
from app.services.chat_events import StreamNotice, TextChunk, ToolUseFinished, ToolUseStarted
from app.services.settings import SettingsService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


# View endpoints for HTML pages


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
            "chat_models": CHAT_MODEL_CHOICES,
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
            "chat_models": CHAT_MODEL_CHOICES,
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


# Conversation CRUD endpoints (chatkit-compatible paths)


@router.get("/api/chat/conversations")
async def list_conversations(
    book_id: int | None = None,
    chat_repo: ChatRepository = Depends(get_chat_repo),
):
    """List chat threads, optionally filtered by book_id."""
    threads = await chat_repo.list_threads(book_id=book_id)
    return [
        {
            "id": str(t.id),
            "title": t.title,
            "book_id": t.book_id,
            "coaching_card_id": t.coaching_card_id,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        }
        for t in threads
    ]


@router.get("/api/chat/conversations/{thread_id}")
async def get_conversation(
    thread_id: int,
    chat_repo: ChatRepository = Depends(get_chat_repo),
):
    """Get all messages for a thread (chatkit format: {messages: [...]})."""
    await chat_repo.get_thread_or_raise(thread_id)
    messages = await chat_repo.list_messages(thread_id)
    return {
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
            if not m.content_blocks  # Hide tool_use/tool_result messages from display
        ]
    }


@router.delete("/api/chat/conversations/{thread_id}")
async def delete_conversation(
    thread_id: int,
    chat_repo: ChatRepository = Depends(get_chat_repo),
):
    """Delete a chat thread and all its messages."""
    thread = await chat_repo.get_thread_or_raise(thread_id)
    await chat_repo.delete_thread(thread)
    return {"ok": True}


# Chat SSE endpoint (chatkit-compatible)


@router.post("/api/chat/chat")
async def send_chat_message(
    request: ChatRequest,
    chat_service: ChatService = Depends(get_chat_service),
    chat_repo: ChatRepository = Depends(get_chat_repo),
    book_repo: BookRepository = Depends(get_book_repo),
):
    """Send a message and get a streaming response.

    Uses chatkit SSE protocol: init -> text/tool_use/tool_done -> done.
    The user message is persisted before streaming begins. The assistant
    response is persisted after the stream completes using an independent
    database session.
    """
    thread_id: int | None = int(request.thread_id) if request.thread_id else None
    book_id: int | None = request.metadata.get("book_id")
    if book_id is not None:
        book_id = int(book_id)

    # Create thread if needed
    if thread_id is None:
        if book_id is not None:
            await book_repo.get_or_raise(book_id)
        title = request.message[:50]
        thread = await chat_repo.create_thread(title=title, book_id=book_id)
        thread_id = thread.id
    else:
        await chat_repo.get_thread_or_raise(thread_id)
        await chat_repo.update_thread_timestamp(thread_id)

    # Save user message immediately
    await chat_repo.create_message(thread_id=thread_id, role="user", content=request.message)

    # Load full conversation history from DB, restoring structured content
    # blocks (tool_use / tool_result) when available.
    messages = await chat_repo.list_messages(thread_id)
    history: list[dict] = []
    for m in messages:
        if m.content_blocks:
            blocks = json.loads(m.content_blocks)
            history.append(cast(dict, {"role": m.role, "content": blocks}))
        else:
            history.append(cast(dict, {"role": m.role, "content": m.content}))

    # Load coaching context if thread is linked to a coaching card
    coaching_prompt: str | None = None
    thread_obj = await chat_repo.get_thread_or_raise(thread_id)
    if thread_obj.coaching_card_id:
        coaching_card = await CoachingRepository(chat_repo.db).get_card(thread_obj.coaching_card_id)
        if coaching_card:
            coaching_prompt = coaching_card.coaching_system_prompt

    # Commit the request session now to release the SQLite lock.
    # The streaming generator uses an independent session (get_async_session)
    # to save the assistant response, which would deadlock if this session
    # still holds a write lock.
    await chat_repo.db.commit()

    events = _chat_events(
        thread_id=thread_id,
        book_id=book_id,
        history=history,
        coaching_prompt=coaching_prompt,
        chat_service=chat_service,
    )
    return EventSourceResponse(stream_chat_events(events), ping=15)


@router.get("/api/chat/threads/{thread_id}/detail")
async def get_thread_detail(
    thread_id: int,
    chat_repo: ChatRepository = Depends(get_chat_repo),
):
    """Get thread metadata including coaching card info."""
    thread = await chat_repo.get_thread_or_raise(thread_id)

    coaching_card_title: str | None = None
    coaching_card_body: str | None = None
    if thread.coaching_card_id:
        coaching_card = await CoachingRepository(chat_repo.db).get_card(thread.coaching_card_id)
        if coaching_card:
            coaching_card_title = coaching_card.title
            coaching_card_body = coaching_card.body

    return {
        "id": str(thread.id),
        "title": thread.title,
        "book_id": thread.book_id,
        "coaching_card_id": thread.coaching_card_id,
        "coaching_card_title": coaching_card_title,
        "coaching_card_body": coaching_card_body,
    }


@router.post("/api/chat/threads/{thread_id}/generate")
async def generate_thread_response(
    thread_id: int,
    chat_service: ChatService = Depends(get_chat_service),
    chat_repo: ChatRepository = Depends(get_chat_repo),
):
    """Stream an AI response for an existing thread's last user message.

    Used to auto-trigger the first coaching response without saving a new
    user message.
    """
    thread = await chat_repo.get_thread_or_raise(thread_id)
    await chat_repo.update_thread_timestamp(thread_id)

    # Load full conversation history
    messages = await chat_repo.list_messages(thread_id)
    history: list[dict] = []
    for m in messages:
        if m.content_blocks:
            blocks = json.loads(m.content_blocks)
            history.append(cast(dict, {"role": m.role, "content": blocks}))
        else:
            history.append(cast(dict, {"role": m.role, "content": m.content}))

    # Load coaching context
    coaching_prompt: str | None = None
    if thread.coaching_card_id:
        coaching_card = await CoachingRepository(chat_repo.db).get_card(thread.coaching_card_id)
        if coaching_card:
            coaching_prompt = coaching_card.coaching_system_prompt

    await chat_repo.db.commit()

    events = _chat_events(
        thread_id=thread_id,
        book_id=thread.book_id,
        history=history,
        coaching_prompt=coaching_prompt,
        chat_service=chat_service,
    )
    return EventSourceResponse(stream_chat_events(events), ping=15)


async def _chat_events(
    *,
    thread_id: int,
    book_id: int | None,
    history: list[dict],
    coaching_prompt: str | None,
    chat_service: ChatService,
) -> Any:
    """Async generator yielding ChatEvent objects for the chatkit SSE protocol."""

    # 1. init event with thread_id
    yield ChatEvent.init(thread_id=str(thread_id))

    # 2. Stream typed events and translate to chatkit SSE events
    full_response = ""
    async for event in chat_service.send_message_from_history(
        history=history,
        book_id=book_id,
        coaching_system_prompt=coaching_prompt,
    ):
        if isinstance(event, ToolUseStarted):
            yield ChatEvent(
                type=ChatEventType.TOOL_USE,
                data=json.dumps(
                    {
                        "tool_name": event.tool_name,
                        "tool_id": event.tool_id,
                    }
                ),
            )
        elif isinstance(event, ToolUseFinished):
            yield ChatEvent(
                type=ChatEventType.TOOL_DONE,
                data=json.dumps(
                    {
                        "tool_id": event.tool_id,
                        "summary": event.summary,
                    }
                ),
            )
        elif isinstance(event, (TextChunk, StreamNotice)):
            full_response += event.text
            yield ChatEvent.text(event.text)

    # 3. Save tool messages and assistant response using independent session
    try:
        async with get_async_session() as session:
            from app.repositories.chat import ChatRepository as ChatRepo
            from app.repositories.chat_metric import ChatMetricRepository

            repo = ChatRepo(session)

            # Save intermediate tool messages (assistant tool_use + user tool_result)
            for tool_msg in chat_service.tool_messages:
                blocks_json = json.dumps(tool_msg["content_blocks"])
                display = "[tool call]" if tool_msg["role"] == "assistant" else "[tool result]"
                await repo.create_message(
                    thread_id=thread_id,
                    role=tool_msg["role"],
                    content=display,
                    content_blocks=blocks_json,
                )

            # Save final assistant text response
            await repo.create_message(thread_id=thread_id, role="assistant", content=full_response)
            await repo.update_thread_timestamp(thread_id)

            if chat_service.last_metrics:
                metric_repo = ChatMetricRepository(session)
                await metric_repo.create(
                    thread_id=thread_id,
                    book_id=book_id,
                    message_count=len(history),
                    **chat_service.last_metrics,
                )
    except Exception:
        logger.exception("Failed to save assistant message for thread %s", thread_id)
        yield ChatEvent.error("Failed to save response")

    # 4. done
    yield ChatEvent.done()
