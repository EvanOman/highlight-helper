"""Thin LLM gateway centralising LiteLLM calls, OTel spans, and cost accounting.

Exports
-------
- ``LLMUsage``   - dataclass capturing per-call token/cost metrics
- ``LLMStream``  - wrapper around an async chunk iterator; ``.usage`` populated after exhaustion
- ``complete()`` - non-streaming call (coaching)
- ``stream()``   - streaming call (chat); ``@asynccontextmanager`` yielding ``LLMStream``
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import litellm
from opentelemetry import context as context_api
from opentelemetry.trace import Status, StatusCode, set_span_in_context

from app.core.config import get_settings
from app.core.model_registry import calculate_cost, normalize_model_id
from app.core.telemetry import get_tracer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Optional LLM gateway routing
# ---------------------------------------------------------------------------
# When BOTH LLM_GATEWAY_BASE_URL and LLM_GATEWAY_API_KEY are set, every
# litellm call in this module is routed through the gateway (enabling
# per-project spend attribution). When either is unset, calls go directly
# to the provider with no change to existing behavior.
_GATEWAY_BASE_URL = os.environ.get("LLM_GATEWAY_BASE_URL")
_GATEWAY_API_KEY = os.environ.get("LLM_GATEWAY_API_KEY")
_GATEWAY_KWARGS: dict[str, Any] = (
    {"api_base": _GATEWAY_BASE_URL, "api_key": _GATEWAY_API_KEY}
    if _GATEWAY_BASE_URL and _GATEWAY_API_KEY
    else {}
)


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------


@dataclass
class LLMUsage:
    """Token counts and cost for a single LLM call."""

    input_tokens: int
    output_tokens: int
    cost_usd: float
    model: str


class LLMStream:
    """Wraps a LiteLLM async streaming response.

    Iterate with ``async for chunk in stream`` to get raw OpenAI-format
    chunks (callers inspect ``delta.content``, ``delta.tool_calls``,
    ``finish_reason``).  After the ``async with`` block exits, ``.usage``
    is populated with the accumulated token counts and cost.
    """

    def __init__(self, raw_response: Any, model: str) -> None:
        self._raw = raw_response
        self._model = model
        self._input_tokens = 0
        self._output_tokens = 0
        self._usage: LLMUsage | None = None

    @property
    def usage(self) -> LLMUsage:
        """Accumulated usage - available only after the stream is exhausted."""
        if self._usage is None:
            raise RuntimeError("usage is not available until the stream is fully consumed")
        return self._usage

    def __aiter__(self):
        return self._iter_chunks()

    async def _iter_chunks(self):
        async for chunk in self._raw:
            # Accumulate usage from the final chunk (stream_options include_usage)
            if hasattr(chunk, "usage") and chunk.usage:
                self._input_tokens += chunk.usage.prompt_tokens or 0
                self._output_tokens += chunk.usage.completion_tokens or 0
            yield chunk

    def _finalise(self) -> None:
        """Compute cost and freeze the usage dataclass."""
        cost = calculate_cost(self._model, self._input_tokens, self._output_tokens)
        self._usage = LLMUsage(
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            cost_usd=cost,
            model=self._model,
        )


# ---------------------------------------------------------------------------
# Non-streaming call
# ---------------------------------------------------------------------------


async def complete(
    model: str,
    messages: list[dict[str, Any]],
    *,
    max_tokens: int = 2048,
    **kwargs: Any,
) -> tuple[str, LLMUsage]:
    """Non-streaming LLM completion (used by coaching).

    Returns
    -------
    tuple[str, LLMUsage]
        The generated text and usage metrics.
    """
    model = normalize_model_id(model)

    tracer = get_tracer("llm")
    span = tracer.start_span(
        "llm.complete",
        attributes={
            "gen_ai.system": "litellm",
            "gen_ai.request.model": model,
        },
    )
    token = context_api.attach(set_span_in_context(span))

    try:
        if get_settings().fake_llm:
            from app.services.llm_fake import fake_completion_text

            text = fake_completion_text(messages)
            input_tokens, output_tokens = 100, 20
        else:
            response = await litellm.acompletion(
                model=model,
                max_tokens=max_tokens,
                messages=messages,
                **_GATEWAY_KWARGS,
                **kwargs,
            )
            text = response.choices[0].message.content or ""
            input_tokens = response.usage.prompt_tokens
            output_tokens = response.usage.completion_tokens
        cost = calculate_cost(model, input_tokens, output_tokens)

        usage = LLMUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            model=model,
        )

        span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
        span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
        span.set_attribute("gen_ai.response.finish_reasons", ["stop"])
        span.set_attribute("llm.cost_usd", cost)
        span.set_status(Status(StatusCode.OK))

        return text, usage

    except Exception as exc:
        span.record_exception(exc)
        span.set_status(Status(StatusCode.ERROR, str(exc)))
        raise
    finally:
        span.end()
        context_api.detach(token)


# ---------------------------------------------------------------------------
# Streaming call
# ---------------------------------------------------------------------------


@asynccontextmanager
async def stream(
    model: str,
    messages: list[dict[str, Any]],
    *,
    max_tokens: int = 16384,
    tools: list[dict] | None = None,
    **kwargs: Any,
):
    """Streaming LLM completion (used by chat).

    Yields an ``LLMStream`` whose async iteration produces raw OpenAI-format
    chunks.  After the ``async with`` block exits, ``stream.usage`` is
    populated with the accumulated token counts and cost.

    The span lifecycle is managed here: a span is opened on entry and closed
    on exit, with usage attributes recorded.
    """
    model = normalize_model_id(model)

    tracer = get_tracer("llm")
    span = tracer.start_span(
        "llm.stream",
        attributes={
            "gen_ai.system": "litellm",
            "gen_ai.request.model": model,
        },
    )
    otel_token = context_api.attach(set_span_in_context(span))

    try:
        if get_settings().fake_llm:
            from app.services.llm_fake import fake_stream_chunks

            raw_response: Any = fake_stream_chunks(messages)
        else:
            call_kwargs: dict[str, Any] = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": messages,
                "stream": True,
                "stream_options": {"include_usage": True},
                **_GATEWAY_KWARGS,
                **kwargs,
            }
            if tools:
                call_kwargs["tools"] = tools

            raw_response = await litellm.acompletion(**call_kwargs)
        llm_stream = LLMStream(raw_response, model)

        yield llm_stream

        # Finalise usage after caller has consumed the stream
        llm_stream._finalise()

        span.set_attribute("gen_ai.usage.input_tokens", llm_stream.usage.input_tokens)
        span.set_attribute("gen_ai.usage.output_tokens", llm_stream.usage.output_tokens)
        span.set_attribute("llm.cost_usd", llm_stream.usage.cost_usd)
        span.set_status(Status(StatusCode.OK))

    except Exception as exc:
        span.record_exception(exc)
        span.set_status(Status(StatusCode.ERROR, str(exc)))
        raise
    finally:
        span.end()
        context_api.detach(otel_token)
