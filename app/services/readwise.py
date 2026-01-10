"""Readwise integration service for syncing highlights."""

from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from app.core.config import get_settings


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
    """Service for syncing highlights to Readwise."""

    BASE_URL = "https://readwise.io/api/v2"

    def __init__(self, api_token: str | None = None) -> None:
        """Initialize the service.

        Args:
            api_token: Readwise API token. If not provided, uses settings.
        """
        if api_token is None:
            settings = get_settings()
            api_token = settings.readwise_api_token
        self._api_token = api_token
        self._client: httpx.AsyncClient | None = None

    @property
    def is_configured(self) -> bool:
        """Check if Readwise is configured with an API token."""
        return bool(self._api_token)

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                headers={
                    "Authorization": f"Token {self._api_token}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def validate_token(self) -> bool:
        """Validate the Readwise API token.

        Returns:
            True if token is valid, False otherwise.
        """
        if not self._api_token:
            return False

        try:
            client = await self._get_client()
            response = await client.get(f"{self.BASE_URL}/auth/")
            return response.status_code == 204
        except httpx.RequestError:
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
        if not self._api_token:
            return ReadwiseSyncResult(
                success=False,
                error="Readwise API token not configured",
            )

        highlight_data: dict = {
            "text": text[:8191],  # Readwise max length
            "title": title[:511],  # Readwise max length
            "author": author[:1024],  # Readwise max length
            "category": "books",
            "source_type": "highlight_helper",
        }

        if note:
            highlight_data["note"] = note[:8191]

        if page_number:
            highlight_data["location"] = page_number
            highlight_data["location_type"] = "page"

        if highlighted_at:
            highlight_data["highlighted_at"] = highlighted_at.isoformat()

        try:
            client = await self._get_client()
            response = await client.post(
                f"{self.BASE_URL}/highlights/",
                json={"highlights": [highlight_data]},
            )

            if response.status_code == 200:
                data = response.json()
                # Response contains array of modified books with their highlights
                if data and len(data) > 0:
                    # Get the first book's modified highlights
                    modified_highlights = data[0].get("modified_highlights", [])
                    if modified_highlights:
                        return ReadwiseSyncResult(
                            success=True,
                            readwise_id=str(modified_highlights[0]),
                        )
                return ReadwiseSyncResult(success=True)
            else:
                return ReadwiseSyncResult(
                    success=False,
                    error=f"Readwise API error: {response.status_code} - {response.text}",
                )
        except httpx.RequestError as e:
            return ReadwiseSyncResult(
                success=False,
                error=f"Network error: {str(e)}",
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
        if not self._api_token:
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
            return ReadwiseBatchResult(total=0, synced=0, failed=0, results=[])

        # Build payload
        readwise_highlights = []
        for h in highlights:
            highlight_data: dict = {
                "text": h["text"][:8191],
                "title": h["title"][:511],
                "author": h["author"][:1024],
                "category": "books",
                "source_type": "highlight_helper",
            }
            if h.get("note"):
                highlight_data["note"] = h["note"][:8191]
            if h.get("page_number"):
                highlight_data["location"] = h["page_number"]
                highlight_data["location_type"] = "page"
            if h.get("highlighted_at"):
                highlight_data["highlighted_at"] = h["highlighted_at"].isoformat()

            readwise_highlights.append(highlight_data)

        try:
            client = await self._get_client()
            response = await client.post(
                f"{self.BASE_URL}/highlights/",
                json={"highlights": readwise_highlights},
            )

            if response.status_code == 200:
                data = response.json()
                # Count all modified highlights across all returned books
                total_synced = 0
                all_ids = []
                for book_result in data:
                    modified = book_result.get("modified_highlights", [])
                    total_synced += len(modified)
                    all_ids.extend(modified)

                results = []
                for i, rid in enumerate(all_ids + [None] * (len(highlights) - len(all_ids))):
                    readwise_id = str(rid) if i < len(all_ids) else None
                    results.append(ReadwiseSyncResult(success=True, readwise_id=readwise_id))
                # Pad results if we got fewer IDs back
                while len(results) < len(highlights):
                    results.append(ReadwiseSyncResult(success=True))

                return ReadwiseBatchResult(
                    total=len(highlights),
                    synced=len(highlights),  # Readwise dedupes, so we assume all sent = synced
                    failed=0,
                    results=results[: len(highlights)],
                )
            else:
                error_msg = f"Readwise API error: {response.status_code}"
                results = [ReadwiseSyncResult(success=False, error=error_msg) for _ in highlights]
                return ReadwiseBatchResult(
                    total=len(highlights),
                    synced=0,
                    failed=len(highlights),
                    results=results,
                )
        except httpx.RequestError as e:
            error_msg = f"Network error: {str(e)}"
            results = [ReadwiseSyncResult(success=False, error=error_msg) for _ in highlights]
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
    import logging

    from app.core.database import get_async_session
    from app.models.highlight import Highlight

    logger = logging.getLogger(__name__)

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

                query = select(Highlight).where(Highlight.id == highlight_id)
                db_result = await db.execute(query)
                highlight = db_result.scalar_one_or_none()

                if highlight:
                    highlight.readwise_id = result.readwise_id
                    highlight.synced_at = datetime.now(tz=timezone.utc)
                    logger.info(f"Auto-synced highlight {highlight_id} to Readwise")
        else:
            logger.warning(f"Failed to auto-sync highlight {highlight_id}: {result.error}")

    except Exception as e:
        logger.error(f"Error during auto-sync of highlight {highlight_id}: {e}")
