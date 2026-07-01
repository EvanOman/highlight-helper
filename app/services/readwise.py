"""Readwise integration service for syncing highlights."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import BackgroundTasks

    from app.models.highlight import Highlight

from readwise_sdk import ReadwiseClient
from readwise_sdk.contrib import HighlightPusher, PushResult, SimpleHighlight
from readwise_sdk.v2 import BookCategory
from readwise_sdk.v2.models import HighlightUpdate
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.telemetry import add_span_attributes, create_span, set_span_status

logger = logging.getLogger(__name__)


# Monkey-patch readwise_sdk paginate() to handle integer cursors.
# The Readwise API returns integer nextPageCursor values, but the SDK
# assumes they are strings and calls .startswith("http") on them.
def _patched_paginate(self, url, params=None, results_key="results", cursor_key="next"):
    params = params.copy() if params else {}
    while True:
        response = self.get(url, params=params)
        data = response.json()
        results = data.get(results_key, [])
        yield from results
        next_cursor = data.get(cursor_key)
        if not next_cursor:
            break
        next_cursor = str(next_cursor)
        if next_cursor.startswith("http"):
            from urllib.parse import parse_qs, urlparse

            parsed = urlparse(next_cursor)
            url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        else:
            params["pageCursor"] = next_cursor


ReadwiseClient.paginate = _patched_paginate  # type: ignore[assignment]


# Readwise API field length limits
READWISE_MAX_TEXT_LENGTH = 8191
READWISE_MAX_TITLE_LENGTH = 511
READWISE_MAX_AUTHOR_LENGTH = 1024
READWISE_MAX_NOTE_LENGTH = 8191


@dataclass
class ReadwiseSyncResult:
    """Result of a Readwise sync operation."""

    success: bool
    readwise_id: str | None = None
    error: str | None = None


@dataclass
class ReadwiseBatchResult:
    """Result of a batch sync operation."""

    total: int
    synced: int
    failed: int
    results: list[ReadwiseSyncResult]


@dataclass
class ReadwiseHighlight:
    """A highlight fetched from Readwise."""

    id: str
    text: str
    note: str | None
    location: int | None
    highlighted_at: datetime | None


@dataclass
class ReadwiseBook:
    """A book fetched from Readwise with its highlights."""

    id: str
    title: str
    author: str
    category: str
    cover_url: str | None
    highlights: list[ReadwiseHighlight] = field(default_factory=list)


@dataclass
class SyncDownProgress:
    """Progress update during sync-down operation."""

    phase: str  # "fetching", "processing", "complete"
    message: str
    books_processed: int = 0
    books_total: int = 0
    highlights_imported: int = 0
    highlights_skipped: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class SyncDownResult:
    """Final result of sync-down operation."""

    success: bool
    books_processed: int
    highlights_imported: int
    highlights_skipped: int
    errors: list[str] = field(default_factory=list)


class ReadwiseService:
    """Service for syncing highlights to Readwise using the readwise-sdk.

    Uses asyncio.to_thread to run the synchronous SDK in a thread pool,
    keeping the FastAPI async event loop responsive.
    """

    def __init__(self, api_token: str | None = None) -> None:
        """Initialize the service.

        Args:
            api_token: Readwise API token. If not provided, uses settings.
        """
        if api_token is None:
            settings = get_settings()
            api_token = settings.readwise_api_token
        self._api_token = api_token

    @property
    def is_configured(self) -> bool:
        """Check if Readwise is configured with an API token."""
        return bool(self._api_token)

    async def __aenter__(self) -> "ReadwiseService":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the service (no-op, SDK handles cleanup via context managers)."""
        pass

    def _create_client(self) -> ReadwiseClient:
        """Create a Readwise client instance."""
        return ReadwiseClient(api_key=self._api_token)

    async def validate_token(self) -> bool:
        """Validate the Readwise API token.

        Returns:
            True if token is valid, False otherwise.
        """
        with create_span("readwise_validate_token"):
            if not self._api_token:
                add_span_attributes(readwise_token_configured=False)
                set_span_status(True)
                return False

            try:

                def _validate() -> bool:
                    client = self._create_client()
                    try:
                        return client.validate_token()
                    finally:
                        client.close()

                is_valid = await asyncio.to_thread(_validate)
                add_span_attributes(
                    readwise_token_configured=True,
                    readwise_token_valid=is_valid,
                )
                set_span_status(True)
                return is_valid
            except Exception as e:
                add_span_attributes(readwise_error=str(e))
                set_span_status(False, str(e))
                return False

    async def send_highlight(
        self,
        text: str,
        title: str,
        author: str,
        note: str | None = None,
        page_number: str | None = None,
        highlighted_at: datetime | None = None,
    ) -> ReadwiseSyncResult:
        """Send a single highlight to Readwise.

        Args:
            text: The highlight text.
            title: Book title.
            author: Book author.
            note: Optional note/annotation.
            page_number: Optional page number.
            highlighted_at: When the highlight was created.

        Returns:
            ReadwiseSyncResult with success status and readwise_id if successful.
        """
        with create_span(
            "readwise_send_highlight",
            {
                "readwise.book_title": title[:100],
                "readwise.text_length": len(text),
                "readwise.has_note": note is not None,
                "readwise.has_page_number": page_number is not None,
            },
        ):
            if not self._api_token:
                set_span_status(False, "Token not configured")
                return ReadwiseSyncResult(
                    success=False,
                    error="Readwise API token not configured",
                )

            try:
                # Convert page_number to int if provided
                location = int(page_number) if page_number and page_number.isdigit() else None

                def _push() -> PushResult:
                    client = self._create_client()
                    try:
                        pusher = HighlightPusher(client)
                        return pusher.push(
                            text=text[:READWISE_MAX_TEXT_LENGTH],
                            title=title[:READWISE_MAX_TITLE_LENGTH],
                            author=author[:READWISE_MAX_AUTHOR_LENGTH],
                            category=BookCategory.BOOKS,
                            source_type="highlight_helper",
                            note=note[:READWISE_MAX_NOTE_LENGTH] if note else None,
                            location=location,
                            highlighted_at=highlighted_at,
                        )
                    finally:
                        client.close()

                result = await asyncio.to_thread(_push)

                if result.success:
                    readwise_id = str(result.highlight_id) if result.highlight_id else None
                    if readwise_id:
                        add_span_attributes(readwise_highlight_id=readwise_id)
                    set_span_status(True)
                    return ReadwiseSyncResult(
                        success=True,
                        readwise_id=readwise_id,
                    )
                error = result.error or "Unknown error"
                add_span_attributes(readwise_error=error)
                set_span_status(False, error)
                return ReadwiseSyncResult(
                    success=False,
                    error=error,
                )
            except Exception as e:
                error = f"Error syncing to Readwise: {e}"
                add_span_attributes(readwise_error=error)
                set_span_status(False, error)
                return ReadwiseSyncResult(
                    success=False,
                    error=error,
                )

    async def update_highlight(
        self,
        readwise_id: str,
        text: str | None = None,
        note: str | None = None,
        page_number: str | None = None,
    ) -> ReadwiseSyncResult:
        """Update an existing highlight on Readwise.

        Args:
            readwise_id: The Readwise highlight ID to update.
            text: Updated highlight text (optional).
            note: Updated note/annotation (optional).
            page_number: Updated page number (optional).

        Returns:
            ReadwiseSyncResult with success status.
        """
        if not self._api_token:
            return ReadwiseSyncResult(
                success=False,
                error="Readwise API token not configured",
            )

        # Build update kwargs
        update_kwargs: dict = {}
        if text is not None:
            update_kwargs["text"] = text[:READWISE_MAX_TEXT_LENGTH]
        if note is not None:
            update_kwargs["note"] = note[:READWISE_MAX_NOTE_LENGTH] if note else ""
        if page_number is not None and page_number.isdigit():
            update_kwargs["location"] = int(page_number)

        if not update_kwargs:
            return ReadwiseSyncResult(
                success=False,
                error="No fields to update",
            )

        try:

            def _update() -> None:
                client = self._create_client()
                try:
                    update = HighlightUpdate(**update_kwargs)
                    client.v2.update_highlight(int(readwise_id), update)
                finally:
                    client.close()

            await asyncio.to_thread(_update)
            return ReadwiseSyncResult(
                success=True,
                readwise_id=readwise_id,
            )
        except Exception as e:
            return ReadwiseSyncResult(
                success=False,
                error=f"Error updating highlight: {e}",
            )

    async def send_highlights(
        self,
        highlights: list[dict],
    ) -> ReadwiseBatchResult:
        """Send multiple highlights to Readwise in a single request.

        Args:
            highlights: List of highlight dicts with keys:
                - text (required)
                - title (required)
                - author (required)
                - note (optional)
                - page_number (optional)
                - highlighted_at (optional)

        Returns:
            ReadwiseBatchResult with sync statistics.
        """
        with create_span(
            "readwise_send_highlights_batch",
            {"readwise.batch_size": len(highlights)},
        ):
            if not self._api_token:
                set_span_status(False, "Token not configured")
                return ReadwiseBatchResult(
                    total=len(highlights),
                    synced=0,
                    failed=len(highlights),
                    results=[
                        ReadwiseSyncResult(success=False, error="Readwise API token not configured")
                        for _ in highlights
                    ],
                )

            if not highlights:
                set_span_status(True)
                return ReadwiseBatchResult(total=0, synced=0, failed=0, results=[])

            try:
                # Convert to SimpleHighlight objects
                simple_highlights = []
                for h in highlights:
                    location = None
                    if h.get("page_number"):
                        with contextlib.suppress(ValueError, TypeError):
                            location = int(h["page_number"])

                    simple_highlights.append(
                        SimpleHighlight(
                            text=h["text"][:READWISE_MAX_TEXT_LENGTH],
                            title=h["title"][:READWISE_MAX_TITLE_LENGTH],
                            author=h.get("author", "")[:READWISE_MAX_AUTHOR_LENGTH],
                            category=BookCategory.BOOKS,
                            source_type="highlight_helper",
                            note=h.get("note", "")[:READWISE_MAX_NOTE_LENGTH]
                            if h.get("note")
                            else None,
                            location=location,
                            location_type="page" if location else None,
                            highlighted_at=h.get("highlighted_at"),
                        )
                    )

                def _push_batch() -> list[PushResult]:
                    client = self._create_client()
                    try:
                        pusher = HighlightPusher(client)
                        return pusher.push_batch(simple_highlights)
                    finally:
                        client.close()

                results = await asyncio.to_thread(_push_batch)

                # Convert results
                sync_results = []
                synced = 0
                failed = 0
                for result in results:
                    if result.success:
                        synced += 1
                        readwise_id = str(result.highlight_id) if result.highlight_id else None
                        sync_results.append(
                            ReadwiseSyncResult(success=True, readwise_id=readwise_id)
                        )
                    else:
                        failed += 1
                        sync_results.append(ReadwiseSyncResult(success=False, error=result.error))

                add_span_attributes(
                    readwise_synced_count=synced,
                    readwise_failed_count=failed,
                )
                set_span_status(True)
                return ReadwiseBatchResult(
                    total=len(highlights),
                    synced=synced,
                    failed=failed,
                    results=sync_results,
                )
            except Exception as e:
                error_msg = f"Error syncing batch: {e}"
                results = [ReadwiseSyncResult(success=False, error=error_msg) for _ in highlights]
                add_span_attributes(
                    readwise_error=error_msg,
                    readwise_synced_count=0,
                    readwise_failed_count=len(highlights),
                )
                set_span_status(False, error_msg)
                return ReadwiseBatchResult(
                    total=len(highlights),
                    synced=0,
                    failed=len(highlights),
                    results=results,
                )

    async def fetch_books(self) -> list[ReadwiseBook]:
        """Fetch all books from Readwise using the export API.

        Returns:
            List of ReadwiseBook objects with category 'books'.
        """
        if not self._api_token:
            return []

        def _fetch_books() -> list[ReadwiseBook]:
            books = []
            client = self._create_client()
            logger.info("Starting Readwise export_highlights fetch...")
            try:
                # Use export_highlights which returns books with their highlights
                for export_book in client.v2.export_highlights():
                    logger.info(
                        "Fetched: %s (%s) - %d highlights",
                        export_book.title,
                        export_book.category,
                        len(export_book.highlights),
                    )
                    # Filter to only books category
                    if export_book.category != "books":
                        continue

                    highlights = [
                        ReadwiseHighlight(
                            id=str(h.id),
                            text=h.text or "",
                            note=h.note,
                            location=h.location,
                            highlighted_at=h.highlighted_at,
                        )
                        for h in export_book.highlights
                    ]
                    books.append(
                        ReadwiseBook(
                            id=str(export_book.user_book_id),
                            title=export_book.title or "Unknown Title",
                            author=export_book.author or "Unknown Author",
                            category=export_book.category or "books",
                            cover_url=export_book.cover_image_url,
                            highlights=highlights,
                        )
                    )
            except Exception as e:
                logger.error("Error during Readwise export iteration: %s", e, exc_info=True)
                raise
            finally:
                client.close()
            logger.info("Readwise fetch complete: %d books", len(books))
            return books

        logger.info("Calling fetch_books via asyncio.to_thread...")
        return await asyncio.to_thread(_fetch_books)

    async def sync_down(
        self,
        db_session: AsyncSession,
    ) -> AsyncIterator[SyncDownProgress]:
        """Import highlights from Readwise into the local database.

        This is a generator that yields progress updates as books are processed.
        Uses readwise_id unique constraint to prevent duplicates.

        Args:
            db_session: SQLAlchemy async session

        Yields:
            SyncDownProgress updates during the import process
        """
        from sqlalchemy import select
        from sqlalchemy.exc import IntegrityError

        from app.models.book import Book
        from app.models.highlight import AnnotationType, Highlight, SyncStatus

        with create_span("readwise_sync_down"):
            if not self._api_token:
                yield SyncDownProgress(
                    phase="complete",
                    message="Readwise not configured",
                    errors=["Readwise API token not configured"],
                )
                return

            # Phase 1: Fetching books from Readwise (streaming via queue)
            yield SyncDownProgress(
                phase="fetching",
                message="Fetching books from Readwise...",
            )

            book_queue: asyncio.Queue[ReadwiseBook | None] = asyncio.Queue()
            loop = asyncio.get_running_loop()

            def _fetch_books_streaming() -> int:
                """Fetch books in a thread, putting each on the queue as it arrives."""
                count = 0
                client = self._create_client()
                logger.info("Starting Readwise export_highlights fetch...")
                try:
                    for export_book in client.v2.export_highlights():
                        logger.info(
                            "Fetched: %s (%s) - %d highlights",
                            export_book.title,
                            export_book.category,
                            len(export_book.highlights),
                        )
                        if export_book.category != "books":
                            continue

                        highlights = [
                            ReadwiseHighlight(
                                id=str(h.id),
                                text=h.text or "",
                                note=h.note,
                                location=h.location,
                                highlighted_at=h.highlighted_at,
                            )
                            for h in export_book.highlights
                        ]
                        rw_book = ReadwiseBook(
                            id=str(export_book.user_book_id),
                            title=export_book.title or "Unknown Title",
                            author=export_book.author or "Unknown Author",
                            category=export_book.category or "books",
                            cover_url=export_book.cover_image_url,
                            highlights=highlights,
                        )
                        loop.call_soon_threadsafe(book_queue.put_nowait, rw_book)
                        count += 1
                except Exception as e:
                    logger.error("Error during Readwise export iteration: %s", e, exc_info=True)
                    raise
                finally:
                    client.close()
                    loop.call_soon_threadsafe(book_queue.put_nowait, None)
                logger.info("Readwise fetch complete: %d books", count)
                return count

            # Launch fetch in background thread
            fetch_task = loop.run_in_executor(None, _fetch_books_streaming)

            # Collect books as they arrive, yielding progress
            readwise_books: list[ReadwiseBook] = []
            try:
                while True:
                    book = await book_queue.get()
                    if book is None:
                        break
                    readwise_books.append(book)
                    yield SyncDownProgress(
                        phase="fetching",
                        message=f"Fetching: {book.title} ({len(readwise_books)} books found...)",
                        books_processed=0,
                        books_total=len(readwise_books),
                    )

                # Wait for the thread to finish and check for exceptions
                await fetch_task
            except Exception as e:
                error_msg = f"Failed to fetch from Readwise: {e}"
                logger.error(error_msg)
                yield SyncDownProgress(
                    phase="complete",
                    message="Failed to fetch from Readwise",
                    errors=[error_msg],
                )
                return

            if not readwise_books:
                yield SyncDownProgress(
                    phase="complete",
                    message="No books found in Readwise",
                    books_processed=0,
                    highlights_imported=0,
                    highlights_skipped=0,
                )
                return

            # Phase 2: Processing books
            total_books = len(readwise_books)
            books_processed = 0
            highlights_imported = 0
            highlights_skipped = 0
            errors: list[str] = []

            for rw_book in readwise_books:
                try:
                    # Skip books with no highlights
                    if not rw_book.highlights:
                        books_processed += 1
                        continue

                    # Find or create the book
                    book_query = select(Book).where(
                        Book.title == rw_book.title,
                        Book.author == rw_book.author,
                    )
                    result = await db_session.execute(book_query)
                    book = result.scalar_one_or_none()

                    if not book:
                        book = Book(
                            title=rw_book.title,
                            author=rw_book.author,
                            cover_url=rw_book.cover_url,
                        )
                        db_session.add(book)
                        await db_session.flush()

                    # Import each highlight
                    for rw_highlight in rw_book.highlights:
                        try:
                            # Use a savepoint so a failure on one highlight
                            # only rolls back that highlight, not the whole batch.
                            async with db_session.begin_nested():
                                # Check if highlight already exists by readwise_id
                                existing_query = select(Highlight).where(
                                    Highlight.readwise_id == rw_highlight.id
                                )
                                existing_result = await db_session.execute(existing_query)
                                if existing_result.scalar_one_or_none():
                                    highlights_skipped += 1
                                    continue

                                # Create new highlight
                                highlight = Highlight(
                                    book_id=book.id,
                                    text=rw_highlight.text,
                                    note=rw_highlight.note,
                                    page_number=(
                                        str(rw_highlight.location)
                                        if rw_highlight.location
                                        else None
                                    ),
                                    type=AnnotationType.HIGHLIGHT,
                                    readwise_id=rw_highlight.id,
                                    synced_at=datetime.now(tz=UTC),
                                    sync_status=SyncStatus.SYNCED,
                                    created_at=rw_highlight.highlighted_at or datetime.now(tz=UTC),
                                )
                                db_session.add(highlight)
                                highlights_imported += 1

                        except IntegrityError:
                            # Savepoint was rolled back; only this highlight is affected
                            highlights_skipped += 1
                        except Exception as e:
                            error_msg = f"Error importing highlight: {e}"
                            logger.warning(error_msg)
                            errors.append(error_msg)

                    await db_session.flush()
                    books_processed += 1

                    # Yield progress update
                    yield SyncDownProgress(
                        phase="processing",
                        message=f"Processing: {rw_book.title}",
                        books_processed=books_processed,
                        books_total=total_books,
                        highlights_imported=highlights_imported,
                        highlights_skipped=highlights_skipped,
                        errors=errors,
                    )

                except Exception as e:
                    # Catch any error for this book and continue with the next
                    error_msg = f"Error processing book '{rw_book.title}': {e}"
                    logger.error(error_msg)
                    errors.append(error_msg)
                    books_processed += 1

            # Phase 3: Complete
            add_span_attributes(
                readwise_books_processed=books_processed,
                readwise_highlights_imported=highlights_imported,
                readwise_highlights_skipped=highlights_skipped,
            )
            set_span_status(True)

            yield SyncDownProgress(
                phase="complete",
                message="Import complete",
                books_processed=books_processed,
                books_total=total_books,
                highlights_imported=highlights_imported,
                highlights_skipped=highlights_skipped,
                errors=errors,
            )


# Lazy initialization for optional service
_readwise_service: ReadwiseService | None = None


def _get_service() -> ReadwiseService:
    """Get or create the singleton service instance."""
    global _readwise_service
    if _readwise_service is None:
        _readwise_service = ReadwiseService()
    return _readwise_service


async def get_readwise_service() -> ReadwiseService:
    """Dependency that provides the Readwise service."""
    return _get_service()


async def sync_highlight_background(
    highlight_id: int,
    book_title: str,
    book_author: str | None,
    text: str,
    note: str | None,
    page_number: str | None,
    created_at: datetime,
    api_token: str | None = None,
) -> None:
    """Background task to sync a highlight to Readwise.

    This function is designed to be called from FastAPI's BackgroundTasks.
    It creates its own database session since it runs after the response.

    Args:
        highlight_id: The local highlight ID to update after sync.
        book_title: Book title for Readwise.
        book_author: Book author for Readwise (defaults to "Unknown Author" if None).
        text: The highlight text.
        note: Optional note/annotation.
        page_number: Optional page number.
        created_at: When the highlight was created.
        api_token: Readwise API token. Falls back to the READWISE_API_TOKEN
            environment variable when None.
    """
    from app.core.database import get_async_session
    from app.models.highlight import Highlight, SyncStatus

    service = ReadwiseService(api_token=api_token)
    if not service.is_configured:
        logger.debug("Readwise not configured, skipping auto-sync")
        return

    try:
        result = await service.send_highlight(
            text=text,
            title=book_title,
            author=book_author or "Unknown Author",
            note=note,
            page_number=page_number,
            highlighted_at=created_at,
        )

        if result.success:
            # Update highlight in database with sync info
            async with get_async_session() as db:
                from sqlalchemy import select

                query = select(Highlight).where(Highlight.id == highlight_id)
                db_result = await db.execute(query)
                highlight = db_result.scalar_one_or_none()

                if highlight:
                    highlight.readwise_id = result.readwise_id
                    highlight.synced_at = datetime.now(tz=UTC)
                    highlight.sync_status = SyncStatus.SYNCED
                    logger.info(f"Auto-synced highlight {highlight_id} to Readwise")
        else:
            logger.warning(f"Failed to auto-sync highlight {highlight_id}: {result.error}")

    except Exception as e:
        logger.error(f"Error during auto-sync of highlight {highlight_id}: {e}")


@dataclass
class PendingSyncResult:
    """Outcome of a batch sync of pending highlights."""

    total: int = 0
    synced: int = 0
    failed: int = 0


async def sync_pending_highlights(
    db: AsyncSession,
    token: str,
    book_id: int | None = None,
) -> PendingSyncResult:
    """Sync all pending (never-synced) highlights to Readwise.

    Shared implementation for the /api/readwise and /api/settings sync-all
    endpoints. Notes are excluded (Readwise doesn't support them). Successful
    syncs are flushed to the session; the caller's session owner commits.
    """
    from app.repositories.highlight import HighlightRepository

    highlight_repo = HighlightRepository(db)
    rows = await highlight_repo.list_unsynced(book_id=book_id)

    notes_count = await highlight_repo.count_unsynced_notes(book_id=book_id)
    if notes_count > 0:
        logger.info(
            "Skipping %d note(s) during sync - notes are not supported by Readwise",
            notes_count,
        )

    if not rows:
        return PendingSyncResult()

    highlight_data = [
        {
            "text": h.text,
            "title": b.title,
            "author": b.author,
            "note": h.note,
            "page_number": h.page_number,
            "highlighted_at": h.created_at,
        }
        for h, b in rows
    ]

    async with ReadwiseService(api_token=token) as service:
        batch_result = await service.send_highlights(highlight_data)

    from app.models.highlight import SyncStatus

    now = datetime.now(tz=UTC)
    for (highlight, _), sync_result in zip(rows, batch_result.results, strict=False):
        if sync_result.success:
            highlight.readwise_id = sync_result.readwise_id
            highlight.synced_at = now
            highlight.sync_status = SyncStatus.SYNCED

    await highlight_repo.flush()

    return PendingSyncResult(
        total=batch_result.total,
        synced=batch_result.synced,
        failed=batch_result.failed,
    )


async def schedule_auto_sync(
    background_tasks: "BackgroundTasks",
    db: AsyncSession,
    highlight: "Highlight",
    book_title: str,
    book_author: str | None,
) -> None:
    """Schedule a background Readwise sync for a new highlight if enabled.

    Checks the app-level auto-sync setting and token; no-op when either is
    missing. Shared by the REST API and the HTML form view.
    """
    from app.services.settings import SettingsService

    app_settings = SettingsService(db)
    auto_sync = await app_settings.get_readwise_auto_sync()
    token = await app_settings.get_readwise_token()
    if not (auto_sync and token):
        return

    # ty ParamSpec bug: kwargs of the task function are inferred incorrectly,
    # book_author is declared `str | None` on sync_highlight_background.
    background_tasks.add_task(
        sync_highlight_background,
        highlight_id=highlight.id,
        book_title=book_title,
        book_author=book_author,  # type: ignore[invalid-argument-type]
        text=highlight.text,
        note=highlight.note,
        page_number=highlight.page_number,
        created_at=highlight.created_at,
        api_token=token,
    )
