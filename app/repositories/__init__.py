"""Repository layer for database access."""

from .book import BookRepository, get_book_repo
from .chat import ChatRepository, get_chat_repo
from .chat_metric import ChatMetricRepository, get_chat_metric_repo
from .highlight import HighlightRepository, get_highlight_repo
from .search import SearchRepository, get_search_repo

__all__ = [
    "BookRepository",
    "ChatMetricRepository",
    "ChatRepository",
    "HighlightRepository",
    "SearchRepository",
    "get_book_repo",
    "get_chat_metric_repo",
    "get_chat_repo",
    "get_highlight_repo",
    "get_search_repo",
]
