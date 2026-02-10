"""Unit tests for ChatMetric model and Anthropic pricing."""

from app.models.api_usage import calculate_cost


class TestAnthropicPricing:
    """Tests for calculate_cost with Anthropic model names."""

    def test_opus_pricing(self):
        """Test cost calculation for Claude Opus."""
        cost = calculate_cost("claude-opus-4-6", input_tokens=1000, output_tokens=500)
        # input: 1000/1M * 15.0 = 0.015, output: 500/1M * 75.0 = 0.0375
        expected = 0.015 + 0.0375
        assert abs(cost - expected) < 1e-10

    def test_sonnet_pricing(self):
        """Test cost calculation for Claude Sonnet."""
        cost = calculate_cost("claude-sonnet-4-5-20250929", input_tokens=1000, output_tokens=500)
        # input: 1000/1M * 3.0 = 0.003, output: 500/1M * 15.0 = 0.0075
        expected = 0.003 + 0.0075
        assert abs(cost - expected) < 1e-10

    def test_haiku_pricing(self):
        """Test cost calculation for Claude Haiku."""
        cost = calculate_cost("claude-haiku-4-5-20251001", input_tokens=1000, output_tokens=500)
        # input: 1000/1M * 0.80 = 0.0008, output: 500/1M * 4.0 = 0.002
        expected = 0.0008 + 0.002
        assert abs(cost - expected) < 1e-10

    def test_unknown_model_uses_default(self):
        """Test that unknown models fall back to default pricing."""
        cost = calculate_cost("unknown-model", input_tokens=1000, output_tokens=500)
        # default: input: 1000/1M * 2.0 = 0.002, output: 500/1M * 15.0 = 0.0075
        expected = 0.002 + 0.0075
        assert abs(cost - expected) < 1e-10
