"""API usage tracking model."""

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class APIUsage(Base):
    """Model for tracking API usage and costs per request."""

    __tablename__ = "api_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    operation: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # e.g., "highlight_extraction"
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    highlight_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # Optional reference to highlight

    def __repr__(self) -> str:
        return f"<APIUsage(id={self.id}, model='{self.model}', cost=${self.cost_usd:.6f})>"


# Token pricing constants (per million tokens)
# GPT-5.2 pricing as of 2026
MODEL_PRICING = {
    "openai/gpt-5.2": {
        "input": 1.75,  # $1.75 per 1M input tokens
        "output": 14.0,  # $14.00 per 1M output tokens
    },
    # Add other models as needed
    "default": {
        "input": 2.0,
        "output": 15.0,
    },
}


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate the cost in USD for a given token usage.

    Args:
        model: The model name (e.g., "openai/gpt-5.2")
        input_tokens: Number of input/prompt tokens
        output_tokens: Number of output/completion tokens

    Returns:
        Cost in USD
    """
    pricing = MODEL_PRICING.get(model, MODEL_PRICING["default"])
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    return input_cost + output_cost
