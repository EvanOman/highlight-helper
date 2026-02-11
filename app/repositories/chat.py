"""Chat repository for database access."""

from datetime import UTC, datetime

from fastapi import Depends
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.models.chat import ChatMessage, ChatThread


class ChatRepository:
    """Repository for ChatThread and ChatMessage database operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_thread_or_raise(self, thread_id: int) -> ChatThread:
        """Get a thread by ID, raising NotFoundError if not found."""
        query = select(ChatThread).where(ChatThread.id == thread_id)
        result = await self.db.execute(query)
        thread = result.scalar_one_or_none()
        if not thread:
            raise NotFoundError("Chat thread not found")
        return thread

    async def list_threads(self, book_id: int | None = None) -> list[ChatThread]:
        """List threads, optionally filtered by book_id, ordered by updated_at desc."""
        query = select(ChatThread).order_by(ChatThread.updated_at.desc())
        if book_id is not None:
            query = query.where(ChatThread.book_id == book_id)
        else:
            query = query.where(ChatThread.book_id.is_(None))
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def create_thread(self, title: str, book_id: int | None = None) -> ChatThread:
        """Create a new chat thread."""
        thread = ChatThread(title=title, book_id=book_id)
        self.db.add(thread)
        await self.db.flush()
        await self.db.refresh(thread)
        return thread

    async def update_thread_timestamp(self, thread_id: int) -> None:
        """Update a thread's updated_at timestamp."""
        stmt = (
            update(ChatThread)
            .where(ChatThread.id == thread_id)
            .values(updated_at=datetime.now(tz=UTC))
        )
        await self.db.execute(stmt)

    async def delete_thread(self, thread: ChatThread) -> None:
        """Delete a thread (cascade deletes messages)."""
        await self.db.delete(thread)

    async def list_messages(self, thread_id: int) -> list[ChatMessage]:
        """List messages for a thread, ordered chronologically."""
        query = (
            select(ChatMessage)
            .where(ChatMessage.thread_id == thread_id)
            .order_by(ChatMessage.created_at.asc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def create_message(
        self, thread_id: int, role: str, content: str, content_blocks: str | None = None
    ) -> ChatMessage:
        """Create a new message in a thread.

        Args:
            thread_id: ID of the thread this message belongs to.
            role: Message role ("user", "assistant").
            content: Plain text content for display.
            content_blocks: Optional JSON-encoded structured content blocks
                (tool_use / tool_result) for API history reconstruction.
        """
        message = ChatMessage(
            thread_id=thread_id, role=role, content=content, content_blocks=content_blocks
        )
        self.db.add(message)
        await self.db.flush()
        await self.db.refresh(message)
        return message


async def get_chat_repo(db: AsyncSession = Depends(get_db)) -> ChatRepository:
    """FastAPI dependency that provides a ChatRepository."""
    return ChatRepository(db)
