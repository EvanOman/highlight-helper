"""Repository layer for database access."""

from .book import BookRepository, get_book_repo
from .highlight import HighlightRepository, get_highlight_repo

__all__ = [
    "BookRepository",
    "HighlightRepository",
    "get_book_repo",
    "get_highlight_repo",
]
