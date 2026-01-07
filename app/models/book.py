"""Book model."""

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Book(Base):
    """Model representing a book."""

    __tablename__ = "books"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    author: Mapped[str] = mapped_column(String(500), nullable=False)
    isbn: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cover_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    highlights: Mapped[list["Highlight"]] = relationship(
        "Highlight",
        back_populates="book",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Book(id={self.id}, title='{self.title}', author='{self.author}')>"
