"""Chat service for conversing with highlights using LiteLLM."""

import json
import logging
import time
from collections.abc import AsyncGenerator, Iterable
from typing import Any

import litellm
from fastapi import Depends
from opentelemetry import context as context_api
from opentelemetry.trace import Status, StatusCode, set_span_in_context
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.model_registry import calculate_cost, get_context_window, normalize_model_id
from app.core.telemetry import get_tracer
from app.repositories.book import BookRepository
from app.repositories.highlight import HighlightRepository
from app.repositories.search import SearchRepository

logger = logging.getLogger(__name__)

# Cap tool results so a single book can't blow out the model's context window.
MAX_BOOK_HIGHLIGHTS_FOR_TOOL = 100

CHAT_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_books",
            "description": (
                "Search for books by title or author. Use when the user mentions "
                "a specific book or wants to find books on a topic."
            ),
            "parameters": {
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
    },
    {
        "type": "function",
        "function": {
            "name": "search_highlights",
            "description": (
                "Search through all highlights and notes across all books. "
                "Use when the user asks about specific topics, concepts, or "
                "wants to find passages they highlighted. Use short, focused "
                "queries (1-3 words) for best results. Call multiple times with "
                "different keywords rather than one long query."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Short search query (1-3 words) for highlight text or notes",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_book_highlights",
            "description": (
                "Get all highlights from a specific book by its ID. "
                "Use after finding a book via search to retrieve its full highlights."
            ),
            "parameters": {
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
    },
]


class ChatService:
    """Service for chatting with highlights using LiteLLM."""

    def __init__(
        self,
        db: AsyncSession,
        chat_model: str | None = None,
    ):
        """Initialize the chat service.

        Args:
            db: Database session for querying highlights
            chat_model: Model ID to use for chat completions
        """
        self.db = db
        settings = get_settings()
        self._chat_model = normalize_model_id(chat_model or settings.chat_model)
        self.last_metrics: dict | None = None
        self._search_repo = SearchRepository(db)
        self._highlight_repo = HighlightRepository(db)
        self._book_repo = BookRepository(db)

    @staticmethod
    def _tool_result_summary(tool_name: str, result: dict) -> str:
        """Build a short human-readable summary of a tool result."""
        if "error" in result:
            return result["error"]
        if tool_name == "search_books":
            n = len(result.get("books", []))
            return f"Found {n} book{'s' if n != 1 else ''}"
        if tool_name == "search_highlights":
            n = len(result.get("highlights", []))
            return f"Found {n} highlight{'s' if n != 1 else ''}"
        if tool_name == "get_book_highlights":
            n = len(result.get("highlights", []))
            return f"Loaded {n} highlight{'s' if n != 1 else ''}"
        return "Done"

    async def _execute_tool(self, tool_name: str, tool_input: dict) -> dict:
        """Execute a tool call and return the result.

        Args:
            tool_name: Name of the tool to execute.
            tool_input: Input arguments for the tool.

        Returns:
            Dict containing the tool result.
        """
        logger.info("Tool call: %s(%s)", tool_name, tool_input)
        if tool_name == "search_books":
            results = await self._search_repo.search_books(tool_input["query"])
            logger.info("search_books returned %d results", len(results))
            return {"books": results}
        if tool_name == "search_highlights":
            results = await self._search_repo.search_highlights(tool_input["query"], limit=20)
            logger.info("search_highlights returned %d results", len(results))
            return {"highlights": results}
        if tool_name == "get_book_highlights":
            book_id = tool_input["book_id"]
            total = await self._highlight_repo.count_for_book(book_id)
            highlights = await self._highlight_repo.list_for_book(
                book_id, limit=MAX_BOOK_HIGHLIGHTS_FOR_TOOL
            )
            logger.info(
                "get_book_highlights(%s) returned %d of %d highlights",
                book_id,
                len(highlights),
                total,
            )
            result: dict = {
                "highlights": [
                    {
                        "text": h.text,
                        "note": h.note,
                        "page": h.page_number,
                    }
                    for h in highlights
                ]
            }
            if total > len(highlights):
                result["note"] = (
                    f"Showing the {len(highlights)} most recent of {total} highlights. "
                    "Use search_highlights to find specific passages."
                )
            return result
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
            book = await self._book_repo.get_by_id(book_id)
            if not book:
                return "No book found with the given ID."

            highlights = await self._highlight_repo.list_for_book(book_id)

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
        book_count = await self._book_repo.get_total_count()
        highlight_count = await self._highlight_repo.get_total_count()

        if book_count == 0:
            return ""

        # Get list of book titles for orientation (starred first)
        book_list = await self._book_repo.list_with_highlight_counts(limit=50)

        lines = [
            f"Your library contains {book_count} books with {highlight_count} total highlights.\n"
        ]
        lines.append("Available books:")
        for book, hl_count in book_list:
            lines.append(f'- "{book.title}" by {book.author} ({hl_count} highlights)')
        if book_count > 50:
            lines.append(f"  ... and {book_count - 50} more books")
        lines.append(
            "\nUse the search_books, search_highlights, and get_book_highlights tools "
            "to find specific content."
        )

        return "\n".join(lines)

    def _build_system_prompt(
        self,
        highlights_context: str,
        book_id: int | None = None,
        coaching_system_prompt: str | None = None,
    ) -> str:
        """Build the system prompt with highlights context.

        Args:
            highlights_context: The formatted highlights to include
            book_id: Optional book ID for scoped conversation
            coaching_system_prompt: If provided, use this instead of default prompt

        Returns:
            The complete system prompt
        """
        if coaching_system_prompt:
            return coaching_system_prompt
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
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({"role": "user", "content": message})

        try:
            response = await litellm.acompletion(
                model=self._chat_model,
                max_tokens=16384,
                messages=messages,
                tools=CHAT_TOOLS,
                stream=True,
            )
            async for chunk in response:
                delta = chunk.choices[0].delta
                if delta.content:
                    yield delta.content
        except Exception as e:
            logger.error(f"Error in chat stream: {e}")
            yield f"I apologize, but I encountered an error: {e!s}"

    async def send_message_from_history(
        self,
        history: Iterable[dict],
        book_id: int | None = None,
        coaching_system_prompt: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream a response given a pre-built conversation history.

        Used by the thread-based chat flow where the API layer loads
        history from the database (already includes the latest user message).

        Handles tool use: when the model requests a tool, this method
        executes it, appends the result, and re-streams until a final
        text response is produced.

        Args:
            history: Full conversation history as list of {role, content} dicts
            book_id: Optional book ID to scope the conversation
            coaching_system_prompt: If provided, use as system prompt instead of default

        Yields:
            Text chunks of the response, plus special ``__tool_use__:``
            prefixed lines so the SSE layer can display tool-use indicators.
        """
        self.last_metrics = None
        self.tool_messages: list[dict] = []
        highlights_context = await self._get_highlights_context(book_id)
        system_prompt = self._build_system_prompt(
            highlights_context, book_id, coaching_system_prompt=coaching_system_prompt
        )

        tracer = get_tracer("chat")
        span = tracer.start_span(
            "chat.stream",
            attributes={
                "gen_ai.system": "litellm",
                "gen_ai.request.model": self._chat_model,
            },
        )
        token = context_api.attach(set_span_in_context(span))

        t_start = time.monotonic()
        t_first_token = None

        # Accumulate total usage across tool-use turns
        total_input_tokens = 0
        total_output_tokens = 0
        final_finish_reason = None

        try:
            messages: list[dict] = [{"role": "system", "content": system_prompt}, *history]

            max_tool_rounds = 5
            for _round in range(max_tool_rounds):
                if _round > 0:
                    yield "\n\n"

                # Accumulate the full response while streaming text
                collected_content = ""
                tool_call_buffers: dict[int, dict] = {}

                response = await litellm.acompletion(
                    model=self._chat_model,
                    max_tokens=16384,
                    messages=messages,
                    tools=CHAT_TOOLS,
                    stream=True,
                    stream_options={"include_usage": True},
                )

                async for chunk in response:
                    delta = chunk.choices[0].delta
                    finish_reason = chunk.choices[0].finish_reason

                    if finish_reason:
                        final_finish_reason = finish_reason

                    # Stream text content
                    if delta.content:
                        if t_first_token is None:
                            t_first_token = time.monotonic()
                        collected_content += delta.content
                        yield delta.content

                    # Accumulate tool calls (they come in pieces across chunks)
                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = tc.index
                            if idx not in tool_call_buffers:
                                tool_call_buffers[idx] = {
                                    "id": tc.id or "",
                                    "name": tc.function.name or "" if tc.function else "",
                                    "arguments": "",
                                }
                            else:
                                if tc.id:
                                    tool_call_buffers[idx]["id"] = tc.id
                                if tc.function and tc.function.name:
                                    tool_call_buffers[idx]["name"] = tc.function.name
                            if tc.function and tc.function.arguments:
                                tool_call_buffers[idx]["arguments"] += tc.function.arguments

                    # Collect usage from the final chunk
                    if hasattr(chunk, "usage") and chunk.usage:
                        total_input_tokens += chunk.usage.prompt_tokens or 0
                        total_output_tokens += chunk.usage.completion_tokens or 0

                # Check if we got tool calls
                if tool_call_buffers:
                    # Build the assistant message with tool calls
                    tool_calls_list = []
                    for idx in sorted(tool_call_buffers.keys()):
                        buf = tool_call_buffers[idx]
                        tool_calls_list.append(
                            {
                                "id": buf["id"],
                                "type": "function",
                                "function": {
                                    "name": buf["name"],
                                    "arguments": buf["arguments"],
                                },
                            }
                        )

                    assistant_msg: dict[str, Any] = {
                        "role": "assistant",
                        "content": collected_content or None,
                        "tool_calls": tool_calls_list,
                    }
                    messages.append(assistant_msg)

                    # Execute each tool and collect results for persistence
                    tool_results_for_persistence = []
                    for tc in tool_calls_list:
                        tool_name = tc["function"]["name"]
                        tool_input = json.loads(tc["function"]["arguments"])

                        yield f"__tool_use__:{json.dumps({'tool': tool_name, 'id': tc['id'], 'input': tool_input})}"
                        tool_result = await self._execute_tool(tool_name, tool_input)
                        summary = self._tool_result_summary(tool_name, tool_result)
                        yield f"__tool_done__:{json.dumps({'tool': tool_name, 'id': tc['id'], 'summary': summary})}"

                        tool_results_for_persistence.append(
                            {"tool_use_id": tc["id"], "result": tool_result}
                        )

                        # Append tool result as a tool message (OpenAI format)
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "content": json.dumps(tool_result),
                            }
                        )

                    # Store serialized tool messages for persistence by the API layer
                    content_blocks: list[dict] = []
                    if collected_content:
                        content_blocks.append({"type": "text", "text": collected_content})
                    content_blocks.extend(
                        {
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": tc["function"]["name"],
                            "input": json.loads(tc["function"]["arguments"]),
                        }
                        for tc in tool_calls_list
                    )

                    self.tool_messages.append(
                        {"role": "assistant", "content_blocks": content_blocks}
                    )
                    self.tool_messages.append(
                        {
                            "role": "user",
                            "content_blocks": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": r["tool_use_id"],
                                    "content": json.dumps(r["result"]),
                                }
                                for r in tool_results_for_persistence
                            ],
                        }
                    )

                    continue  # loop back for next round
                else:
                    # No tool calls - we're done
                    break

            # Warn user if response was truncated
            if final_finish_reason == "length":
                yield "\n\n---\n*[Response truncated due to length limit]*"

            # Warn if all rounds used tools without a final text response
            if final_finish_reason == "tool_calls":
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

            context_window = get_context_window(self._chat_model)
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
                "stop_reason": final_finish_reason,
                "context_utilization_pct": round(context_utilization_pct, 2),
            }

            # Set span attributes with final metrics
            span.set_attribute("gen_ai.usage.input_tokens", total_input_tokens)
            span.set_attribute("gen_ai.usage.output_tokens", total_output_tokens)
            span.set_attribute("gen_ai.response.finish_reasons", [final_finish_reason or "unknown"])
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
