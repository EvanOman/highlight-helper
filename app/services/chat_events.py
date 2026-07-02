"""Typed events yielded by ChatService.send_message_from_history.

These replace the old ``__tool_use__:`` / ``__tool_done__:`` string-prefix
protocol with proper dataclass instances that the SSE layer can match on
with ``isinstance``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TextChunk:
    """A chunk of streamed assistant text."""

    text: str


@dataclass(frozen=True, slots=True)
class ToolUseStarted:
    """The model has requested a tool call and it is about to execute."""

    tool_name: str
    tool_id: str
    tool_input: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolUseFinished:
    """A tool call has completed."""

    tool_id: str
    tool_name: str
    summary: str


@dataclass(frozen=True, slots=True)
class StreamNotice:
    """An informational notice injected into the stream.

    Used for truncation warnings, max-rounds notices, etc.
    """

    text: str


# Union type for all events the generator can yield
ChatEvent = TextChunk | ToolUseStarted | ToolUseFinished | StreamNotice
