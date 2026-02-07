"""Service protocol definitions for structural typing."""

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Protocol

from app.services.book_lookup import BookInfo
from app.services.readwise import (
    ReadwiseBatchResult,
    ReadwiseSyncResult,
    SyncDownProgress,
)


class SyncService(Protocol):
    """Protocol for a highlight sync service (e.g. Readwise)."""

    @property
    def is_configured(self) -> bool: ...

    async def validate_token(self) -> bool: ...

    async def send_highlight(
        self,
        text: str,
        title: str,
        author: str,
        note: str | None = None,
        page_number: str | None = None,
        highlighted_at: datetime | None = None,
    ) -> ReadwiseSyncResult: ...

    async def update_highlight(
        self,
        readwise_id: str,
        text: str | None = None,
        note: str | None = None,
        page_number: str | None = None,
    ) -> ReadwiseSyncResult: ...

    async def send_highlights(
        self,
        highlights: list[dict],
    ) -> ReadwiseBatchResult: ...

    async def sync_down(
        self,
        db_session: object,
    ) -> AsyncIterator[SyncDownProgress]: ...

    async def close(self) -> None: ...


class BookLookupProvider(Protocol):
    """Protocol for a book lookup service (e.g. Google Books API)."""

    async def search_books(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[BookInfo]: ...

    async def search_by_isbn(
        self,
        isbn: str,
    ) -> BookInfo | None: ...

    async def close(self) -> None: ...
