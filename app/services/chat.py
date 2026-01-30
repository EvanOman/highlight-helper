"""Chat service for conversing with highlights using Anthropic API."""

import logging
from collections.abc import AsyncGenerator

from anthropic import AsyncAnthropic
from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.models.book import Book
from app.models.highlight import Highlight

logger = logging.getLogger(__name__)


class ChatService:
    """Service for chatting with highlights using Claude."""

    def __init__(self, db: AsyncSession, client: AsyncAnthropic | None = None):
        """Initialize the chat service.

        Args:
            db: Database session for querying highlights
            client: Optional Anthropic client for dependency injection in tests
        """
        self.db = db
        settings = get_settings()
        self._client = client or AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def _get_highlights_context(self, book_id: int | None = None) -> str:
        """Fetch highlights from the database and format as context.

        Args:
            book_id: Optional book ID to filter highlights

        Returns:
            Formatted string of highlights for the system prompt
        """
        if book_id:
            # Get book info and its highlights
            book_result = await self.db.execute(select(Book).where(Book.id == book_id))
            book = book_result.scalar_one_or_none()

            if not book:
                return "No book found with the given ID."

            highlights_query = (
                select(Highlight)
                .where(Highlight.book_id == book_id)
                .order_by(Highlight.created_at.desc())
            )
            result = await self.db.execute(highlights_query)
            highlights = result.scalars().all()

            if not highlights:
                return (
                    f'Book: "{book.title}" by {book.author}\n\nNo highlights found for this book.'
                )

            context_parts = [f'Book: "{book.title}" by {book.author}\n\nHighlights:']
            for i, h in enumerate(highlights, 1):
                entry = f"\n{i}. "
                if h.text:
                    entry += f'"{h.text}"'
                if h.page_number:
                    entry += f" (page {h.page_number})"
                if h.note:
                    entry += f"\n   Note: {h.note}"
                context_parts.append(entry)

            return "\n".join(context_parts)
        else:
            # Get all highlights with book info
            query = select(Highlight, Book).join(Book).order_by(Highlight.created_at.desc())
            result = await self.db.execute(query)
            rows = result.all()

            if not rows:
                return "No highlights found in the library."

            context_parts = ["All Highlights:\n"]
            current_book = None

            for highlight, book in rows:
                if current_book != book.id:
                    context_parts.append(f'\n--- "{book.title}" by {book.author} ---')
                    current_book = book.id

                entry = "\n- "
                if highlight.text:
                    entry += f'"{highlight.text}"'
                if highlight.page_number:
                    entry += f" (page {highlight.page_number})"
                if highlight.note:
                    entry += f"\n  Note: {highlight.note}"
                context_parts.append(entry)

            return "\n".join(context_parts)

    def _build_system_prompt(self, highlights_context: str, book_id: int | None = None) -> str:
        """Build the system prompt with highlights context.

        Args:
            highlights_context: The formatted highlights to include
            book_id: Optional book ID for scoped conversation

        Returns:
            The complete system prompt
        """
        if book_id:
            base_prompt = """You are a helpful assistant that helps users explore and discuss \
their book highlights. You are currently focused on a specific book.

Be conversational and insightful. Help users:
- Recall specific passages they've highlighted
- Find connections between ideas within the book
- Explore themes and patterns in their highlights
- Discuss and reflect on the content

Here are the user's highlights from this book:

"""
        else:
            base_prompt = """You are a helpful assistant that helps users explore and discuss \
their book highlights across all their books.

Be conversational and insightful. Help users:
- Find connections between ideas across different books
- Recall specific passages they've highlighted
- Explore themes and patterns in their reading
- Compare perspectives from different authors
- Reflect on their reading journey

Here are all the user's highlights:

"""
        return base_prompt + highlights_context

    async def send_message(
        self,
        message: str,
        book_id: int | None = None,
        conversation_history: list[dict] | None = None,
    ) -> AsyncGenerator[str, None]:
        """Send a message and stream the response.

        Args:
            message: User's message
            book_id: Optional book ID to scope the conversation
            conversation_history: Optional list of previous messages

        Yields:
            Chunks of the response text
        """
        # Get highlights context
        highlights_context = await self._get_highlights_context(book_id)

        # Build system prompt
        system_prompt = self._build_system_prompt(highlights_context, book_id)

        # Build messages list
        messages = []
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({"role": "user", "content": message})

        try:
            async with self._client.messages.stream(
                model="claude-sonnet-4-20250514",
                max_tokens=2048,
                system=system_prompt,
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    yield text
        except Exception as e:
            logger.error(f"Error in chat stream: {e}")
            yield f"I apologize, but I encountered an error: {str(e)}"


async def get_chat_service(db: AsyncSession = Depends(get_db)) -> ChatService:
    """Dependency that provides the chat service."""
    return ChatService(db)
