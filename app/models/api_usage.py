"""API usage tracking model."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# Re-exported for backward compatibility; the registry is the source of truth.
from app.core.model_registry import calculate_cost

__all__ = ["APIUsage", "calculate_cost"]


class APIUsage(Base):
    """Model for tracking API usage and costs per request."""

    __tablename__ = "api_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    operation: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # e.g., "highlight_extraction"
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 8), default=0.0, nullable=False)
    highlight_id: Mapped[int | None] = mapped_column(
        ForeignKey("highlights.id", ondelete="SET NULL"), nullable=True
    )

    def __repr__(self) -> str:
        return f"<APIUsage(id={self.id}, model='{self.model}', cost=${self.cost_usd:.6f})>"
