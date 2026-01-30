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


class AnnotationType(str, Enum):
    """Type of annotation (highlight or note)."""

    HIGHLIGHT = "highlight"  # A highlighted passage from the book
    NOTE = "note"  # A standalone note (no highlight text required)


class Highlight(Base):
    """Model representing a book highlight or standalone note."""

    __tablename__ = "highlights"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), nullable=False)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)  # Nullable for notes
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Annotation type (highlight or note)
    type: Mapped[AnnotationType] = mapped_column(
        SQLEnum(AnnotationType),
        default=AnnotationType.HIGHLIGHT,
        server_default=AnnotationType.HIGHLIGHT.value,
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
        preview = self.text[:50] if self.text else self.note[:50] if self.note else ""
        return f"<Highlight(id={self.id}, type={self.type.value}, book_id={self.book_id}, preview='{preview}...')>"
