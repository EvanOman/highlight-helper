"""Highlight model."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.book import Book


class SyncStatus(str, Enum):
    """Sync status for highlights."""

    PENDING = "pending"  # Not yet synced
    SYNCED = "synced"  # Successfully synced to Readwise
    REMOVED_EXTERNALLY = "removed_externally"  # Synced but removed by user in Readwise


class Highlight(Base):
    """Model representing a book highlight."""

    __tablename__ = "highlights"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Readwise sync fields
    readwise_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    sync_status: Mapped[SyncStatus] = mapped_column(
        SQLEnum(SyncStatus),
        default=SyncStatus.PENDING,
        server_default=SyncStatus.PENDING.value,
        nullable=False,
    )

    # Relationships
    book: Mapped[Book] = relationship("Book", back_populates="highlights")

    def __repr__(self) -> str:
        return f"<Highlight(id={self.id}, book_id={self.book_id}, text='{self.text[:50]}...')>"
