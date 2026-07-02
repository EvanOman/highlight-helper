"""Chat service for conversing with highlights using LiteLLM."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncGenerator, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.model_registry import get_context_window, normalize_model_id
from app.repositories.book import BookRepository
from app.repositories.highlight import HighlightRepository
from app.repositories.search import SearchRepository
from app.services import llm as llm_gateway
from app.services.chat_events import (
    StreamNotice,
    TextChunk,
    ToolUseFinished,
    ToolUseStarted,
)
from app.services.llm import LLMUsage

logger = logging.getLogger(__name__)

# Cap tool results so a single book can't blow out the model's context window.
MAX_BOOK_HIGHLIGHTS_FOR_TOOL = 100


# ---------------------------------------------------------------------------
# Self-registering tool registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ChatToolDef:
    """A single tool definition: schema for the API + async handler."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[ChatService, dict], Any]  # async (service, input) -> dict


class _ToolRegistry:
    """Collects tool definitions and exposes them in OpenAI function-call format."""

    def __init__(self) -> None:
        self._tools: dict[str, ChatToolDef] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
    ) -> Callable:
        """Decorator that registers an async handler as a chat tool."""

        def decorator(fn: Callable) -> Callable:
            self._tools[name] = ChatToolDef(
                name=name,
                description=description,
                parameters=parameters,
                handler=fn,
            )
            return fn

        return decorator

    def as_tool_params(self) -> list[dict]:
        """Return the list in OpenAI function-call format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    def get(self, name: str) -> ChatToolDef | None:
        return self._tools.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self._tools


_registry = _ToolRegistry()


@_registry.register(
    name="search_books",
    description=(
        "Search for books by title or author. Use when the user mentions "
        "a specific book or wants to find books on a topic."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query for book title or author",
            }
        },
        "required": ["query"],
    },
)
async def _tool_search_books(service: ChatService, tool_input: dict) -> dict:
    results = await service._search_repo.search_books(tool_input["query"])
    logger.info("search_books returned %d results", len(results))
    return {"books": results}


@_registry.register(
    name="search_highlights",
    description=(
        "Search through all highlights and notes across all books. "
        "Use when the user asks about specific topics, concepts, or "
        "wants to find passages they highlighted. Use short, focused "
        "queries (1-3 words) for best results. Call multiple times with "
        "different keywords rather than one long query."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Short search query (1-3 words) for highlight text or notes",
            }
        },
        "required": ["query"],
    },
)
async def _tool_search_highlights(service: ChatService, tool_input: dict) -> dict:
    results = await service._search_repo.search_highlights(tool_input["query"], limit=20)
    logger.info("search_highlights returned %d results", len(results))
    return {"highlights": results}


@_registry.register(
    name="get_book_highlights",
    description=(
        "Get all highlights from a specific book by its ID. "
        "Use after finding a book via search to retrieve its full highlights."
    ),
    parameters={
        "type": "object",
        "properties": {
            "book_id": {
                "type": "integer",
                "description": "The book ID to get highlights for",
            }
        },
        "required": ["book_id"],
    },
)
async def _tool_get_book_highlights(service: ChatService, tool_input: dict) -> dict:
    book_id = tool_input["book_id"]
    total = await service._highlight_repo.count_for_book(book_id)
    highlights = await service._highlight_repo.list_for_book(
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


# Module-level constant for the OpenAI-format tool list
CHAT_TOOLS: list[dict] = _registry.as_tool_params()


# ---------------------------------------------------------------------------
# Result type for _stream_completion
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _CompletionResult:
    """Collected outputs from a single streaming round."""

    text_chunks: list[str] = field(default_factory=list)
    tool_call_buffers: dict[int, dict] = field(default_factory=dict)
    finish_reason: str | None = None
    usage: LLMUsage | None = None
    t_first_token: float | None = None


# ---------------------------------------------------------------------------
# ChatService
# ---------------------------------------------------------------------------


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

    # -- tool execution (registry-backed) ------------------------------------

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
        """Execute a tool call via the registry and return the result."""
        logger.info("Tool call: %s(%s)", tool_name, tool_input)
        tool_def = _registry.get(tool_name)
        if tool_def is None:
            return {"error": f"Unknown tool: {tool_name}"}
        return await tool_def.handler(self, tool_input)

    # -- context / prompt building -------------------------------------------

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

    # -- streaming (legacy non-thread path) ----------------------------------

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
            async with llm_gateway.stream(
                model=self._chat_model,
                messages=messages,
                max_tokens=16384,
                tools=CHAT_TOOLS,
            ) as llm_stream:
                async for chunk in llm_stream:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        yield delta.content
        except Exception as e:
            logger.error(f"Error in chat stream: {e}")
            yield f"I apologize, but I encountered an error: {e!s}"

    # -- decomposed private methods for send_message_from_history ------------

    async def _stream_completion(
        self,
        messages: list[dict],
    ) -> _CompletionResult:
        """Run one LLM streaming round via the gateway and collect results.

        This is the *only* method that touches ``llm_gateway.stream``.
        Returns a ``_CompletionResult`` with collected text chunks,
        buffered tool calls, finish reason, usage, and first-token time.
        """
        result = _CompletionResult()

        async with llm_gateway.stream(
            model=self._chat_model,
            messages=messages,
            max_tokens=16384,
            tools=CHAT_TOOLS,
        ) as llm_stream:
            async for chunk in llm_stream:
                delta = chunk.choices[0].delta
                finish_reason = chunk.choices[0].finish_reason

                if finish_reason:
                    result.finish_reason = finish_reason

                # Collect text content
                if delta.content:
                    if result.t_first_token is None:
                        result.t_first_token = time.monotonic()
                    result.text_chunks.append(delta.content)

                # Accumulate tool calls (they come in pieces across chunks)
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in result.tool_call_buffers:
                            result.tool_call_buffers[idx] = {
                                "id": tc.id or "",
                                "name": tc.function.name or "" if tc.function else "",
                                "arguments": "",
                            }
                        else:
                            if tc.id:
                                result.tool_call_buffers[idx]["id"] = tc.id
                            if tc.function and tc.function.name:
                                result.tool_call_buffers[idx]["name"] = tc.function.name
                        if tc.function and tc.function.arguments:
                            result.tool_call_buffers[idx]["arguments"] += tc.function.arguments

        # Usage from the gateway (populated after context manager exit)
        result.usage = llm_stream.usage

        return result

    async def _run_tool_calls(
        self,
        collected_content: str,
        tool_call_buffers: dict[int, dict],
        messages: list[dict],
    ) -> AsyncGenerator[ToolUseStarted | ToolUseFinished, None]:
        """Execute tool calls from a streaming round.

        For each buffered tool call:
        1. Yields a ``ToolUseStarted`` event
        2. Executes the tool
        3. Yields a ``ToolUseFinished`` event

        Also mutates *messages* (appending the assistant + tool messages)
        and appends to ``self.tool_messages`` for persistence.
        """
        # Build the ordered tool_calls list from buffers
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

        # Append assistant message with tool_calls to conversation
        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": collected_content or None,
            "tool_calls": tool_calls_list,
        }
        messages.append(assistant_msg)

        # Execute each tool and collect results
        tool_results_for_persistence = []
        for tc in tool_calls_list:
            tool_name = tc["function"]["name"]
            tool_input = json.loads(tc["function"]["arguments"])

            yield ToolUseStarted(
                tool_name=tool_name,
                tool_id=tc["id"],
                tool_input=tool_input,
            )
            tool_result = await self._execute_tool(tool_name, tool_input)
            summary = self._tool_result_summary(tool_name, tool_result)
            yield ToolUseFinished(
                tool_id=tc["id"],
                tool_name=tool_name,
                summary=summary,
            )

            tool_results_for_persistence.append({"tool_use_id": tc["id"], "result": tool_result})

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

        self.tool_messages.append({"role": "assistant", "content_blocks": content_blocks})
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

    def _record_metrics(
        self,
        *,
        t_start: float,
        t_first_token: float | None,
        t_end: float,
        total_input_tokens: int,
        total_output_tokens: int,
        total_cost_usd: float,
        final_finish_reason: str | None,
    ) -> None:
        """Build ``self.last_metrics`` from accumulated round data."""
        total_tokens = total_input_tokens + total_output_tokens

        ttft_ms = ((t_first_token - t_start) * 1000) if t_first_token else None
        total_latency_ms = (t_end - t_start) * 1000
        generation_time = t_end - (t_first_token or t_start)
        tokens_per_sec = (total_output_tokens / generation_time) if generation_time > 0 else None

        context_window = get_context_window(self._chat_model)
        context_utilization_pct = (total_input_tokens / context_window) * 100

        self.last_metrics = {
            "model": self._chat_model,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "total_tokens": total_tokens,
            "cost_usd": total_cost_usd,
            "ttft_ms": round(ttft_ms, 1) if ttft_ms is not None else None,
            "total_latency_ms": round(total_latency_ms, 1),
            "tokens_per_sec": round(tokens_per_sec, 1) if tokens_per_sec is not None else None,
            "stop_reason": final_finish_reason,
            "context_utilization_pct": round(context_utilization_pct, 2),
        }

    # -- main public generator -----------------------------------------------

    async def send_message_from_history(
        self,
        history: Iterable[dict],
        book_id: int | None = None,
        coaching_system_prompt: str | None = None,
    ) -> AsyncGenerator[TextChunk | ToolUseStarted | ToolUseFinished | StreamNotice, None]:
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
            Typed event instances (TextChunk, ToolUseStarted,
            ToolUseFinished, StreamNotice).
        """
        self.last_metrics = None
        self.tool_messages: list[dict] = []
        highlights_context = await self._get_highlights_context(book_id)
        system_prompt = self._build_system_prompt(
            highlights_context, book_id, coaching_system_prompt=coaching_system_prompt
        )

        t_start = time.monotonic()
        t_first_token: float | None = None

        # Accumulate total usage across tool-use turns
        total_input_tokens = 0
        total_output_tokens = 0
        total_cost_usd = 0.0
        final_finish_reason: str | None = None

        try:
            messages: list[dict] = [{"role": "system", "content": system_prompt}, *history]

            max_tool_rounds = 5
            for _round in range(max_tool_rounds):
                if _round > 0:
                    yield TextChunk("\n\n")

                completion = await self._stream_completion(messages)

                # Yield text chunks to the caller
                for chunk_text in completion.text_chunks:
                    yield TextChunk(chunk_text)

                # Track first-token time across rounds
                if t_first_token is None and completion.t_first_token is not None:
                    t_first_token = completion.t_first_token

                final_finish_reason = completion.finish_reason

                # Accumulate usage from this round
                if completion.usage:
                    total_input_tokens += completion.usage.input_tokens
                    total_output_tokens += completion.usage.output_tokens
                    total_cost_usd += completion.usage.cost_usd

                # Check if we got tool calls
                if completion.tool_call_buffers:
                    collected_content = "".join(completion.text_chunks)
                    async for event in self._run_tool_calls(
                        collected_content, completion.tool_call_buffers, messages
                    ):
                        yield event
                    continue  # loop back for next round
                else:
                    break  # no tool calls - we're done

            # Warn user if response was truncated
            if final_finish_reason == "length":
                yield StreamNotice("\n\n---\n*[Response truncated due to length limit]*")

            # Warn if all rounds used tools without a final text response
            if final_finish_reason == "tool_calls":
                yield StreamNotice(
                    "\n\n---\n*[Reached maximum tool use rounds. Try a more specific question.]*"
                )

            t_end = time.monotonic()

            self._record_metrics(
                t_start=t_start,
                t_first_token=t_first_token,
                t_end=t_end,
                total_input_tokens=total_input_tokens,
                total_output_tokens=total_output_tokens,
                total_cost_usd=total_cost_usd,
                final_finish_reason=final_finish_reason,
            )

        except Exception as e:
            logger.error(f"Error in chat stream: {e}")
            yield TextChunk(f"I apologize, but I encountered an error: {e!s}")


async def get_chat_service(db: AsyncSession = Depends(get_db)) -> ChatService:
    """Dependency that provides the chat service."""
    from app.services.settings import SettingsService

    settings_svc = SettingsService(db)
    chat_model = await settings_svc.get_chat_model()
    return ChatService(db, chat_model=chat_model)
