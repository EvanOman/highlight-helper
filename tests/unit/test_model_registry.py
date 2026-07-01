"""Tests for the unified model registry."""

from app.core.model_registry import (
    CHAT_MODEL_CHOICES,
    MODEL_REGISTRY,
    calculate_cost,
    get_context_window,
    get_model_info,
    is_valid_chat_model,
    normalize_model_id,
)


class TestNormalizeModelId:
    def test_canonical_id_unchanged(self):
        assert normalize_model_id("anthropic/claude-opus-4-6") == "anthropic/claude-opus-4-6"

    def test_bare_name_gets_prefix(self):
        assert normalize_model_id("claude-opus-4-6") == "anthropic/claude-opus-4-6"
        assert normalize_model_id("gpt-5.4") == "openai/gpt-5.4"

    def test_groq_nested_prefix(self):
        bare = "meta-llama/llama-4-scout-17b-16e-instruct"
        assert normalize_model_id(bare) == f"groq/{bare}"

    def test_unknown_model_passes_through(self):
        assert normalize_model_id("some/unknown-model") == "some/unknown-model"


class TestCalculateCost:
    def test_prefixed_and_bare_names_price_identically(self):
        prefixed = calculate_cost("anthropic/claude-opus-4-6", 1000, 500)
        bare = calculate_cost("claude-opus-4-6", 1000, 500)
        assert prefixed == bare
        # Opus: $15/1M in, $75/1M out
        assert prefixed == (1000 / 1_000_000) * 15.0 + (500 / 1_000_000) * 75.0

    def test_unknown_model_uses_default_pricing(self):
        cost = calculate_cost("unknown-model", 1_000_000, 1_000_000)
        assert cost == 2.0 + 15.0

    def test_zero_tokens_zero_cost(self):
        assert calculate_cost("claude-haiku-4-5-20251001", 0, 0) == 0.0


class TestModelInfo:
    def test_lookup_tolerates_bare_names(self):
        info = get_model_info("claude-sonnet-4-5-20250929")
        assert info is not None
        assert info.id == "anthropic/claude-sonnet-4-5-20250929"

    def test_context_window_known_and_unknown(self):
        assert get_context_window("anthropic/claude-opus-4-6") == 200_000
        assert get_context_window("openai/gpt-5.4") == 400_000
        assert get_context_window("mystery-model") == 200_000
        assert get_context_window("mystery-model", default=8192) == 8192

    def test_chat_choices_are_canonical_and_chat_capable(self):
        assert CHAT_MODEL_CHOICES  # non-empty
        for model_id, label in CHAT_MODEL_CHOICES:
            assert model_id in MODEL_REGISTRY
            assert MODEL_REGISTRY[model_id].chat_capable
            assert label

    def test_is_valid_chat_model(self):
        assert is_valid_chat_model("claude-opus-4-6")
        assert is_valid_chat_model("anthropic/claude-haiku-4-5-20251001")
        assert not is_valid_chat_model("openai/gpt-5.4")  # not chat-capable
        assert not is_valid_chat_model("made-up-model")
