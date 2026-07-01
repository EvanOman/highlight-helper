"""Single source of truth for LLM model metadata.

Every model used anywhere in the app (chat, coaching, vision extraction)
is registered here with its canonical LiteLLM id (provider-prefixed),
display label, pricing, and context window. All lookups normalize bare
model names (e.g. ``claude-opus-4-6``) to their canonical prefixed form
(``anthropic/claude-opus-4-6``) so callers can pass either.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelInfo:
    """Metadata for a single LLM model."""

    id: str  # Canonical LiteLLM id, provider-prefixed (e.g. "anthropic/claude-opus-4-6")
    label: str  # Human-readable name for UI dropdowns
    input_price: float  # USD per 1M input tokens
    output_price: float  # USD per 1M output tokens
    context_window: int = 200_000
    chat_capable: bool = False  # Shown in the chat model picker


_MODELS = [
    ModelInfo(
        id="anthropic/claude-opus-4-6",
        label="Claude Opus 4.6",
        input_price=15.0,
        output_price=75.0,
        chat_capable=True,
    ),
    ModelInfo(
        id="anthropic/claude-sonnet-4-5-20250929",
        label="Claude Sonnet 4.5",
        input_price=3.0,
        output_price=15.0,
        chat_capable=True,
    ),
    ModelInfo(
        id="anthropic/claude-haiku-4-5-20251001",
        label="Claude Haiku 4.5",
        input_price=0.80,
        output_price=4.0,
        chat_capable=True,
    ),
    ModelInfo(
        id="openai/gpt-5.2",
        label="GPT-5.2",
        input_price=1.75,
        output_price=14.0,
        context_window=400_000,
    ),
    ModelInfo(
        id="openai/gpt-5.4",
        label="GPT-5.4",
        input_price=1.75,
        output_price=14.0,
        context_window=400_000,
    ),
    ModelInfo(
        id="groq/meta-llama/llama-4-scout-17b-16e-instruct",
        label="Llama 4 Scout (Groq)",
        input_price=0.11,
        output_price=0.34,
        context_window=128_000,
    ),
]

MODEL_REGISTRY: dict[str, ModelInfo] = {m.id: m for m in _MODELS}

# Used when a model isn't registered; conservative middle-of-road pricing.
DEFAULT_PRICING = ModelInfo(
    id="default",
    label="Unknown model",
    input_price=2.0,
    output_price=15.0,
)

# (canonical id, label) pairs for the chat model picker.
CHAT_MODEL_CHOICES: list[tuple[str, str]] = [(m.id, m.label) for m in _MODELS if m.chat_capable]


def normalize_model_id(model: str) -> str:
    """Resolve a possibly-bare model name to its canonical prefixed id.

    Returns the input unchanged when no registered model matches, so
    unknown models still flow through to LiteLLM as-is.
    """
    if model in MODEL_REGISTRY:
        return model
    for canonical in MODEL_REGISTRY:
        if canonical.endswith(f"/{model}"):
            return canonical
    return model


def get_model_info(model: str) -> ModelInfo | None:
    """Look up model metadata, tolerating bare (unprefixed) names."""
    return MODEL_REGISTRY.get(normalize_model_id(model))


def is_valid_chat_model(model: str) -> bool:
    """Whether the model may be selected as the chat/coaching model."""
    info = get_model_info(model)
    return info is not None and info.chat_capable


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate the cost in USD for a given token usage.

    Args:
        model: Model name, bare or provider-prefixed.
        input_tokens: Number of input/prompt tokens.
        output_tokens: Number of output/completion tokens.

    Returns:
        Cost in USD.
    """
    info = get_model_info(model) or DEFAULT_PRICING
    input_cost = (input_tokens / 1_000_000) * info.input_price
    output_cost = (output_tokens / 1_000_000) * info.output_price
    return input_cost + output_cost


def get_context_window(model: str, default: int = 200_000) -> int:
    """Context window size for a model, tolerating bare names."""
    info = get_model_info(model)
    return info.context_window if info else default
