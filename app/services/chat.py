"""Chat service for conversing with highlights using Anthropic API."""

import json
import logging
import time
from collections.abc import AsyncGenerator, Iterable
from typing import Any, cast

from anthropic import AsyncAnthropic
from anthropic.types import MessageParam, ToolParam
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
from app.repositories.highlight import HighlightRepository
from app.repositories.search import SearchRepository

logger = logging.getLogger(__name__)

MODEL_CONTEXT_WINDOWS = {
    "claude-opus-4-6": 200_000,
    "claude-sonnet-4-5-20250929": 200_000,
    "claude-haiku-4-5-20251001": 200_000,
}

CHAT_TOOLS: list[ToolParam] = [
    {
        "name": "search_books",
        "description": (
            "Search for books by title or author. Use when the user mentions "
            "a specific book or wants to find books on a topic."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query for book title or author",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_highlights",
        "description": (
            "Search through all highlights and notes across all books. "
            "Use when the user asks about specific topics, concepts, or "
            "wants to find passages they highlighted."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query for highlight text or notes",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_book_highlights",
        "description": (
            "Get all highlights from a specific book by its ID. "
            "Use after finding a book via search to retrieve its full highlights."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "book_id": {
                    "type": "integer",
                    "description": "The book ID to get highlights for",
                }
            },
            "required": ["book_id"],
        },
    },
]


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
        self._search_repo = SearchRepository(db)
        self._highlight_repo = HighlightRepository(db)

    async def _execute_tool(self, tool_name: str, tool_input: dict) -> dict:
        """Execute a tool call and return the result.

        Args:
            tool_name: Name of the tool to execute.
            tool_input: Input arguments for the tool.

        Returns:
            Dict containing the tool result.
        """
        if tool_name == "search_books":
            results = await self._search_repo.search_books(tool_input["query"])
            return {"books": results}
        if tool_name == "search_highlights":
            results = await self._search_repo.search_highlights(tool_input["query"])
            return {"highlights": results}
        if tool_name == "get_book_highlights":
            highlights = await self._highlight_repo.list_for_book(tool_input["book_id"])
            return {
                "highlights": [
                    {
                        "text": h.text,
                        "note": h.note,
                        "page": h.page_number,
                    }
                    for h in highlights
                ]
            }
        return {"error": f"Unknown tool: {tool_name}"}

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
        # For global chat, don't load all highlights into context.
        # The model has search tools to find relevant content on demand.
        # Just provide a summary of what's available.
        from sqlalchemy import func

        book_count_result = await self.db.execute(select(func.count(Book.id)))
        book_count = book_count_result.scalar() or 0
        highlight_count_result = await self.db.execute(select(func.count(Highlight.id)))
        highlight_count = highlight_count_result.scalar() or 0

        if book_count == 0:
            return ""

        # Get list of book titles for orientation
        books_result = await self.db.execute(
            select(Book.title, Book.author, func.count(Highlight.id))
            .outerjoin(Highlight)
            .group_by(Book.id)
            .order_by(Book.is_starred.desc(), Book.title)
            .limit(50)
        )
        book_list = books_result.all()

        lines = [
            f"Your library contains {book_count} books with {highlight_count} total highlights.\n"
        ]
        lines.append("Available books:")
        for title, author, hl_count in book_list:
            lines.append(f'- "{title}" by {author} ({hl_count} highlights)')
        if book_count > 50:
            lines.append(f"  ... and {book_count - 50} more books")
        lines.append(
            "\nUse the search_books, search_highlights, and get_book_highlights tools "
            "to find specific content."
        )

        return "\n".join(lines)

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

Response Style:
- Be concise and conversational. This is a chat, not an essay.
- For open-ended questions (themes, summaries, recommendations), start with 3-4 key points \
at a high level.
- Keep initial responses brief (~150-200 words). Use bullet points and bold for scannability.
- After your initial response, invite the user to go deeper: "Want me to explore any of \
these further?" or "I can go deeper on any of these — which interests you?"
- Only give lengthy, detailed responses when the user explicitly asks for depth (e.g., \
"tell me more about X", "give me a detailed analysis", "expand on that").
- When quoting highlights, cite 1-2 key quotes per point, not every relevant highlight.

Help users:
- Recall specific passages they've highlighted
- Find connections between ideas within the book
- Explore themes and patterns in their highlights
- Discuss and reflect on the content

You have access to search tools that can find books and highlights. Use them when the user \
asks about specific topics, books, or wants to find particular passages.

Here are the user's highlights from this book:

"""
        else:
            base_prompt = """You are a helpful assistant that helps users explore and discuss \
their book highlights across all their books.

Response Style:
- Be concise and conversational. This is a chat, not an essay.
- For open-ended questions (themes, summaries, recommendations), start with 3-4 key points \
at a high level.
- Keep initial responses brief (~150-200 words). Use bullet points and bold for scannability.
- After your initial response, invite the user to go deeper: "Want me to explore any of \
these further?" or "I can go deeper on any of these — which interests you?"
- Only give lengthy, detailed responses when the user explicitly asks for depth (e.g., \
"tell me more about X", "give me a detailed analysis", "expand on that").
- When quoting highlights, cite 1-2 key quotes per point, not every relevant highlight.

Help users:
- Find connections between ideas across different books
- Recall specific passages they've highlighted
- Explore themes and patterns in their reading
- Compare perspectives from different authors
- Reflect on their reading journey

You have access to search tools (search_books, search_highlights, get_book_highlights) \
that can find books and highlights in the user's library. ALWAYS use these tools to look up \
specific content — the library summary below lists what's available, but the actual highlight \
text is only accessible through the tools.

Here is a summary of the user's library:

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
                max_tokens=16384,
                system=system_prompt,
                messages=messages,
                tools=CHAT_TOOLS,
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

        Handles Anthropic tool use: when the model requests a tool, this
        method executes it, appends the result, and re-streams until a
        final text response is produced.

        Args:
            history: Full conversation history as list of {role, content} dicts
            book_id: Optional book ID to scope the conversation

        Yields:
            Text chunks of the response, plus special ``__tool_use__:``
            prefixed lines so the SSE layer can display tool-use indicators.
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

        # Accumulate total usage across tool-use turns
        total_input_tokens = 0
        total_output_tokens = 0
        final_stop_reason = None

        try:
            messages: list = list(history)  # copy so we can append tool results

            max_tool_rounds = 5
            final_message = None
            for _round in range(max_tool_rounds):
                if _round > 0:
                    yield "\n\n"

                async with self._client.messages.stream(
                    model=self._chat_model,
                    max_tokens=16384,
                    system=system_prompt,
                    messages=messages,
                    tools=CHAT_TOOLS,
                ) as stream:
                    # Stream text deltas to the caller in real time
                    async for event in stream:
                        if (
                            hasattr(event, "type")
                            and event.type == "content_block_delta"
                            and hasattr(event, "delta")
                            and hasattr(event.delta, "text")
                        ):
                            if t_first_token is None:
                                t_first_token = time.monotonic()
                            yield cast(Any, event).delta.text

                    final_message = await stream.get_final_message()

                # Accumulate token usage
                total_input_tokens += final_message.usage.input_tokens
                total_output_tokens += final_message.usage.output_tokens
                final_stop_reason = final_message.stop_reason

                if final_message.stop_reason == "tool_use":
                    # Signal tool use to the SSE layer
                    tool_use_blocks = [
                        cast(Any, b) for b in final_message.content if b.type == "tool_use"
                    ]

                    for block in tool_use_blocks:
                        # Yield a special marker the SSE handler can detect
                        yield f"__tool_use__:{json.dumps({'tool': block.name, 'input': block.input})}"

                    # Append the full assistant message (with both text + tool_use blocks)
                    messages.append({"role": "assistant", "content": final_message.content})

                    # Execute each tool and build tool_result entries
                    tool_result_content = []
                    for block in tool_use_blocks:
                        tool_result = await self._execute_tool(block.name, block.input)
                        tool_result_content.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps(tool_result),
                            }
                        )

                    messages.append({"role": "user", "content": tool_result_content})
                    continue  # loop back to stream again with tool results
                else:
                    break  # got a final text response, we're done

            # Warn user if response was truncated
            if final_message and final_message.stop_reason == "max_tokens":
                yield "\n\n---\n*[Response truncated due to length limit]*"

            # Warn if all rounds used tools without a final text response
            if final_message and final_message.stop_reason == "tool_use":
                yield "\n\n---\n*[Reached maximum tool use rounds. Try a more specific question.]*"

            t_end = time.monotonic()

            total_tokens = total_input_tokens + total_output_tokens

            ttft_ms = ((t_first_token - t_start) * 1000) if t_first_token else None
            total_latency_ms = (t_end - t_start) * 1000
            generation_time = t_end - (t_first_token or t_start)
            tokens_per_sec = (
                (total_output_tokens / generation_time) if generation_time > 0 else None
            )
            cost_usd = calculate_cost(self._chat_model, total_input_tokens, total_output_tokens)

            context_window = MODEL_CONTEXT_WINDOWS.get(self._chat_model, 200_000)
            context_utilization_pct = (total_input_tokens / context_window) * 100

            self.last_metrics = {
                "model": self._chat_model,
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "total_tokens": total_tokens,
                "cost_usd": cost_usd,
                "ttft_ms": round(ttft_ms, 1) if ttft_ms is not None else None,
                "total_latency_ms": round(total_latency_ms, 1),
                "tokens_per_sec": round(tokens_per_sec, 1) if tokens_per_sec is not None else None,
                "stop_reason": final_stop_reason,
                "context_utilization_pct": round(context_utilization_pct, 2),
            }

            # Set span attributes with final metrics
            span.set_attribute("gen_ai.usage.input_tokens", total_input_tokens)
            span.set_attribute("gen_ai.usage.output_tokens", total_output_tokens)
            span.set_attribute("gen_ai.response.finish_reasons", [final_stop_reason or "unknown"])
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
