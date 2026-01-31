"""Readwise integration service for syncing highlights."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from readwise_sdk import ReadwiseClient
from readwise_sdk.contrib import HighlightPusher, PushResult, SimpleHighlight
from readwise_sdk.v2 import BookCategory

from app.core.config import get_settings
from app.core.telemetry import add_span_attributes, create_span, set_span_status

logger = logging.getLogger(__name__)


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
                            text=text[:8191],  # Readwise max length
                            title=title[:511],  # Readwise max length
                            author=author[:1024],  # Readwise max length
                            category=BookCategory.BOOKS,
                            source_type="highlight_helper",
                            note=note[:8191] if note else None,
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
                else:
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
            update_kwargs["text"] = text[:8191]
        if note is not None:
            update_kwargs["note"] = note[:8191] if note else ""
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
                    client.v2.update_highlight(int(readwise_id), **update_kwargs)
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
                        try:
                            location = int(h["page_number"])
                        except (ValueError, TypeError):
                            pass

                    simple_highlights.append(
                        SimpleHighlight(
                            text=h["text"][:8191],
                            title=h["title"][:511],
                            author=h.get("author", "")[:1024],
                            category=BookCategory.BOOKS,
                            source_type="highlight_helper",
                            note=h.get("note", "")[:8191] if h.get("note") else None,
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
    book_author: str,
    text: str,
    note: str | None,
    page_number: str | None,
    created_at: datetime,
) -> None:
    """Background task to sync a highlight to Readwise.

    This function is designed to be called from FastAPI's BackgroundTasks.
    It creates its own database session since it runs after the response.

    Args:
        highlight_id: The local highlight ID to update after sync.
        book_title: Book title for Readwise.
        book_author: Book author for Readwise.
        text: The highlight text.
        note: Optional note/annotation.
        page_number: Optional page number.
        created_at: When the highlight was created.
    """
    from app.core.database import get_async_session
    from app.models.highlight import Highlight

    service = _get_service()
    if not service.is_configured:
        logger.debug("Readwise not configured, skipping auto-sync")
        return

    try:
        result = await service.send_highlight(
            text=text,
            title=book_title,
            author=book_author,
            note=note,
            page_number=page_number,
            highlighted_at=created_at,
        )

        if result.success:
            # Update highlight in database with sync info
            async with get_async_session() as db:
                from sqlalchemy import select

                from app.models.highlight import SyncStatus

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


async def sync_highlight_background_with_token(
    highlight_id: int,
    book_title: str,
    book_author: str,
    text: str,
    note: str | None,
    page_number: str | None,
    created_at: datetime,
    api_token: str,
) -> None:
    """Background task to sync a highlight to Readwise with explicit token.

    This version accepts the API token as a parameter instead of reading from
    environment settings, allowing use with app-level settings.

    Args:
        highlight_id: The local highlight ID to update after sync.
        book_title: Book title for Readwise.
        book_author: Book author for Readwise.
        text: The highlight text.
        note: Optional note/annotation.
        page_number: Optional page number.
        created_at: When the highlight was created.
        api_token: The Readwise API token.
    """
    from app.core.database import get_async_session
    from app.models.highlight import Highlight

    service = ReadwiseService(api_token=api_token)

    try:
        result = await service.send_highlight(
            text=text,
            title=book_title,
            author=book_author,
            note=note,
            page_number=page_number,
            highlighted_at=created_at,
        )

        if result.success:
            # Update highlight in database with sync info
            async with get_async_session() as db:
                from sqlalchemy import select

                from app.models.highlight import SyncStatus

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
