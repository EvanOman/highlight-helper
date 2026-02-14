"""Coaching card model for proactive reading engagement."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

if TYPE_CHECKING:
    pass


class CoachingCardType(str, Enum):
    CROSS_BOOK_CONNECTION = "cross_book_connection"
    COMPREHENSION_CHECK = "comprehension_check"
    SPACED_REVIEW = "spaced_review"


class CoachingCardStatus(str, Enum):
    PENDING = "pending"
    SHOWN = "shown"
    ENGAGED = "engaged"
    DISMISSED = "dismissed"
    EXPIRED = "expired"


class CoachingCard(Base):
    """A proactive coaching card that prompts reader engagement."""

    __tablename__ = "coaching_cards"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    card_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    chat_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    coaching_system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    highlight_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_book_id: Mapped[int | None] = mapped_column(
        ForeignKey("books.id", ondelete="SET NULL"), nullable=True
    )
    secondary_book_id: Mapped[int | None] = mapped_column(
        ForeignKey("books.id", ondelete="SET NULL"), nullable=True
    )
    thread_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_threads.id", ondelete="SET NULL"), nullable=True
    )
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 8), default=0.0, nullable=False)
    eligible_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    shown_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<CoachingCard(id={self.id}, type='{self.card_type}', status='{self.status}')>"
