"""Database models."""

from app.models.book import Book
from app.models.highlight import Highlight, SyncStatus
from app.models.settings import AppSetting

__all__ = ["AppSetting", "Book", "Highlight", "SyncStatus"]
