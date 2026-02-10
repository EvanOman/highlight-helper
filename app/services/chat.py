"""Chat service for conversing with highlights using Anthropic API."""

import logging
import time
from collections.abc import AsyncGenerator, Iterable

from anthropic import AsyncAnthropic
from anthropic.types import MessageParam
from fastapi import Depends
from opentelemetry import context as context_api
from opentelemetry.trace import Status, StatusCode, set_span_in_context
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.telemetry import get_tracer
from app.models.api_usage import calculate_cost
from app.models.book import Book
from app.models.highlight import Highlight

logger = logging.getLogger(__name__)

MODEL_CONTEXT_WINDOWS = {
    "claude-opus-4-6": 200_000,
    "claude-sonnet-4-5-20250929": 200_000,
    "claude-haiku-4-5-20251001": 200_000,
}


class ChatService:
    """Service for chatting with highlights using Claude."""

    def __init__(
        self,
        db: AsyncSession,
        client: AsyncAnthropic | None = None,
        chat_model: str | None = None,
    ):
        """Initialize the chat service.

        Args:
            db: Database session for querying highlights
            client: Optional Anthropic client for dependency injection in tests
            chat_model: Model ID to use for chat completions
        """
        self.db = db
        settings = get_settings()
        self._client = client or AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._chat_model = chat_model or settings.chat_model
        self.last_metrics: dict | None = None

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
                model=self._chat_model,
                max_tokens=2048,
                system=system_prompt,
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    yield text
        except Exception as e:
            logger.error(f"Error in chat stream: {e}")
            yield f"I apologize, but I encountered an error: {e!s}"

    async def send_message_from_history(
        self,
        history: Iterable[MessageParam],
        book_id: int | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream a response given a pre-built conversation history.

        Used by the thread-based chat flow where the API layer loads
        history from the database (already includes the latest user message).

        Args:
            history: Full conversation history as list of {role, content} dicts
            book_id: Optional book ID to scope the conversation

        Yields:
            Chunks of the response text
        """
        self.last_metrics = None
        highlights_context = await self._get_highlights_context(book_id)
        system_prompt = self._build_system_prompt(highlights_context, book_id)

        tracer = get_tracer("chat")
        span = tracer.start_span(
            "chat.stream",
            attributes={
                "gen_ai.system": "anthropic",
                "gen_ai.request.model": self._chat_model,
            },
        )
        token = context_api.attach(set_span_in_context(span))

        t_start = time.monotonic()
        t_first_token = None

        try:
            async with self._client.messages.stream(
                model=self._chat_model,
                max_tokens=2048,
                system=system_prompt,
                messages=history,
            ) as stream:
                async for text in stream.text_stream:
                    if t_first_token is None:
                        t_first_token = time.monotonic()
                    yield text

                # Still inside `async with stream` — get final message for usage
                final_message = await stream.get_final_message()

            t_end = time.monotonic()

            input_tokens = final_message.usage.input_tokens
            output_tokens = final_message.usage.output_tokens
            total_tokens = input_tokens + output_tokens
            stop_reason = final_message.stop_reason

            ttft_ms = ((t_first_token - t_start) * 1000) if t_first_token else None
            total_latency_ms = (t_end - t_start) * 1000
            generation_time = t_end - (t_first_token or t_start)
            tokens_per_sec = (output_tokens / generation_time) if generation_time > 0 else None
            cost_usd = calculate_cost(self._chat_model, input_tokens, output_tokens)

            context_window = MODEL_CONTEXT_WINDOWS.get(self._chat_model, 200_000)
            context_utilization_pct = (input_tokens / context_window) * 100

            self.last_metrics = {
                "model": self._chat_model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "cost_usd": cost_usd,
                "ttft_ms": round(ttft_ms, 1) if ttft_ms is not None else None,
                "total_latency_ms": round(total_latency_ms, 1),
                "tokens_per_sec": round(tokens_per_sec, 1) if tokens_per_sec is not None else None,
                "stop_reason": stop_reason,
                "context_utilization_pct": round(context_utilization_pct, 2),
            }

            # Set span attributes with final metrics
            span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
            span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
            span.set_attribute("gen_ai.response.finish_reasons", [stop_reason or "unknown"])
            if ttft_ms is not None:
                span.set_attribute("chat.ttft_ms", round(ttft_ms, 1))
            span.set_attribute("chat.total_latency_ms", round(total_latency_ms, 1))
            if tokens_per_sec is not None:
                span.set_attribute("chat.tokens_per_sec", round(tokens_per_sec, 1))
            span.set_attribute("chat.cost_usd", cost_usd)
            span.set_status(Status(StatusCode.OK))

        except Exception as e:
            logger.error(f"Error in chat stream: {e}")
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            yield f"I apologize, but I encountered an error: {e!s}"
        finally:
            span.end()
            context_api.detach(token)


async def get_chat_service(db: AsyncSession = Depends(get_db)) -> ChatService:
    """Dependency that provides the chat service."""
    from app.services.settings import SettingsService

    settings_svc = SettingsService(db)
    chat_model = await settings_svc.get_chat_model()
    return ChatService(db, chat_model=chat_model)
