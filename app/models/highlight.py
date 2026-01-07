"""Highlight model."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


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

    # Relationships
    book: Mapped["Book"] = relationship("Book", back_populates="highlights")

    def __repr__(self) -> str:
        return f"<Highlight(id={self.id}, book_id={self.book_id}, text='{self.text[:50]}...')>"
