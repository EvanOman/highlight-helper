"""Unit tests for the LLM gateway (app/services/llm.py)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.llm import LLMUsage, complete, stream


class TestComplete:
    """Tests for llm.complete()."""

    @patch("app.services.llm.litellm")
    async def test_returns_text_and_usage(self, mock_litellm):
        """complete() returns (text, LLMUsage) from a non-streaming response."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Hello world"))]
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        text, usage = await complete(
            model="anthropic/claude-haiku-4-5-20251001",
            messages=[{"role": "user", "content": "hi"}],
        )

        assert text == "Hello world"
        assert isinstance(usage, LLMUsage)
        assert usage.input_tokens == 100
        assert usage.output_tokens == 50
        assert usage.cost_usd > 0
        assert usage.model == "anthropic/claude-haiku-4-5-20251001"

        # Verify litellm.acompletion was called with correct kwargs
        mock_litellm.acompletion.assert_called_once()
        call_kwargs = mock_litellm.acompletion.call_args
        assert call_kwargs.kwargs["model"] == "anthropic/claude-haiku-4-5-20251001"
        assert call_kwargs.kwargs["max_tokens"] == 2048

    @patch("app.services.llm.litellm")
    async def test_normalizes_bare_model_name(self, mock_litellm):
        """complete() normalizes a bare model name to its canonical form."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="ok"))]
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        _, usage = await complete(
            model="claude-haiku-4-5-20251001",
            messages=[{"role": "user", "content": "hi"}],
        )

        # Should have been normalized to the prefixed form
        assert usage.model == "anthropic/claude-haiku-4-5-20251001"
        call_kwargs = mock_litellm.acompletion.call_args.kwargs
        assert call_kwargs["model"] == "anthropic/claude-haiku-4-5-20251001"

    @patch("app.services.llm.litellm")
    async def test_empty_content_returns_empty_string(self, mock_litellm):
        """complete() returns '' when the response has no text content."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content=None))]
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 0
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        text, _ = await complete(
            model="anthropic/claude-haiku-4-5-20251001",
            messages=[{"role": "user", "content": "hi"}],
        )

        assert text == ""

    @patch("app.services.llm.litellm")
    async def test_reraises_api_error(self, mock_litellm):
        """complete() re-raises exceptions from litellm."""
        mock_litellm.acompletion = AsyncMock(side_effect=Exception("boom"))

        with pytest.raises(Exception, match="boom"):
            await complete(
                model="anthropic/claude-haiku-4-5-20251001",
                messages=[{"role": "user", "content": "hi"}],
            )


class TestStream:
    """Tests for llm.stream()."""

    @patch("app.services.llm.litellm")
    async def test_yields_chunks_and_populates_usage(self, mock_litellm):
        """stream() yields raw chunks and populates .usage after context exit."""
        usage_obj = MagicMock()
        usage_obj.prompt_tokens = 200
        usage_obj.completion_tokens = 80

        chunk1 = MagicMock()
        chunk1.usage = None
        chunk2 = MagicMock()
        chunk2.usage = None
        chunk3 = MagicMock()
        chunk3.usage = usage_obj

        async def _fake_stream():
            for c in [chunk1, chunk2, chunk3]:
                yield c

        mock_litellm.acompletion = AsyncMock(return_value=_fake_stream())

        async with stream(
            model="anthropic/claude-haiku-4-5-20251001",
            messages=[{"role": "user", "content": "hi"}],
        ) as s:
            collected = [chunk async for chunk in s]

        assert len(collected) == 3
        assert s.usage.input_tokens == 200
        assert s.usage.output_tokens == 80
        assert s.usage.cost_usd > 0
        assert s.usage.model == "anthropic/claude-haiku-4-5-20251001"

    @patch("app.services.llm.litellm")
    async def test_stream_handles_error(self, mock_litellm):
        """stream() propagates errors from litellm.acompletion."""
        mock_litellm.acompletion = AsyncMock(side_effect=Exception("Stream failed"))

        with pytest.raises(Exception, match="Stream failed"):
            async with stream(
                model="anthropic/claude-haiku-4-5-20251001",
                messages=[{"role": "user", "content": "hi"}],
            ) as s:
                async for _chunk in s:
                    pass

    @patch("app.services.llm.litellm")
    async def test_stream_passes_tools(self, mock_litellm):
        """stream() passes tools through to litellm.acompletion."""
        tools = [{"type": "function", "function": {"name": "test", "parameters": {}}}]

        async def _empty_stream():
            return
            yield

        mock_litellm.acompletion = AsyncMock(return_value=_empty_stream())

        async with stream(
            model="anthropic/claude-haiku-4-5-20251001",
            messages=[{"role": "user", "content": "hi"}],
            tools=tools,
        ) as s:
            async for _ in s:
                pass

        call_kwargs = mock_litellm.acompletion.call_args.kwargs
        assert call_kwargs["tools"] == tools
        assert call_kwargs["stream"] is True
        assert call_kwargs["stream_options"] == {"include_usage": True}
