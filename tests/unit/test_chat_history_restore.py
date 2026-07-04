"""Tests for restoring persisted tool-use history into OpenAI format.

Regression coverage for the production error:
    litellm.APIConnectionError: Invalid user message ... invalid content type=tool_result
Persisted content_blocks are Anthropic-style; the restore path must convert
them to OpenAI chat-completion messages before they reach LiteLLM.
"""

import json
from types import SimpleNamespace

from app.api.chat import _restore_history


def _msg(role: str, content: str, blocks: list | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        role=role,
        content=content,
        content_blocks=json.dumps(blocks) if blocks is not None else None,
    )


def _tool_history() -> list[SimpleNamespace]:
    """A realistic persisted thread: user q -> tool round -> final answer."""
    return [
        _msg("user", "Which books discuss focus?"),
        _msg(
            "assistant",
            "[tool call]",
            blocks=[
                {"type": "text", "text": "Let me search."},
                {
                    "type": "tool_use",
                    "id": "toolu_123",
                    "name": "search_highlights",
                    "input": {"query": "focus"},
                },
            ],
        ),
        _msg(
            "user",
            "[tool result]",
            blocks=[
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_123",
                    "content": json.dumps({"highlights": [{"text": "Deep work matters"}]}),
                }
            ],
        ),
        _msg("assistant", "Deep Work by Cal Newport discusses focus."),
        _msg("user", "he is talking about runtime fast -- have another example?"),
    ]


class TestRestoreHistory:
    def test_plain_messages_pass_through(self):
        history = _restore_history([_msg("user", "hi"), _msg("assistant", "hello")])
        assert history == [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]

    def test_tool_use_blocks_become_tool_calls(self):
        history = _restore_history(_tool_history())
        assistant_tool_msg = history[1]
        assert assistant_tool_msg["role"] == "assistant"
        assert assistant_tool_msg["content"] == "Let me search."
        assert assistant_tool_msg["tool_calls"] == [
            {
                "id": "toolu_123",
                "type": "function",
                "function": {
                    "name": "search_highlights",
                    "arguments": json.dumps({"query": "focus"}),
                },
            }
        ]

    def test_tool_result_blocks_become_tool_role_messages(self):
        history = _restore_history(_tool_history())
        tool_msg = history[2]
        assert tool_msg["role"] == "tool"
        assert tool_msg["tool_call_id"] == "toolu_123"
        assert "Deep work matters" in tool_msg["content"]

    def test_assistant_tool_use_without_text_has_none_content(self):
        history = _restore_history(
            [
                _msg(
                    "assistant",
                    "[tool call]",
                    blocks=[{"type": "tool_use", "id": "t1", "name": "search_books", "input": {}}],
                )
            ]
        )
        assert history[0]["content"] is None
        assert history[0]["tool_calls"][0]["id"] == "t1"

    def test_non_string_tool_result_content_is_serialized(self):
        history = _restore_history(
            [
                _msg(
                    "user",
                    "[tool result]",
                    blocks=[{"type": "tool_result", "tool_use_id": "t1", "content": {"books": []}}],
                )
            ]
        )
        assert history[0]["content"] == json.dumps({"books": []})

    def test_restored_history_passes_litellm_validation(self):
        """The exact validator that raised in production must accept the output."""
        from litellm.utils import validate_chat_completion_user_messages

        history = _restore_history(_tool_history())
        # Raises on invalid user messages (the production failure mode)
        validate_chat_completion_user_messages(messages=history)  # type: ignore[invalid-argument-type]
