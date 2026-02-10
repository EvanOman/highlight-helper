"""Integration tests for the Readwise sync-down SSE endpoint."""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from sqlalchemy import select

from app.models.book import Book
from app.models.highlight import Highlight, SyncStatus
from app.services.readwise import ReadwiseService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_export_highlight(
    *,
    id: int,
    text: str,
    note: str | None = None,
    location: int | None = None,
    highlighted_at: datetime | None = None,
) -> MagicMock:
    """Create a mock export highlight object matching the Readwise SDK shape."""
    h = MagicMock()
    h.id = id
    h.text = text
    h.note = note
    h.location = location
    h.highlighted_at = highlighted_at or datetime(2024, 6, 15, tzinfo=UTC)
    return h


def _make_export_book(
    *,
    user_book_id: int,
    title: str,
    author: str,
    category: str = "books",
    cover_image_url: str | None = None,
    highlights: list | None = None,
) -> MagicMock:
    """Create a mock ExportBook object matching the Readwise SDK shape."""
    book = MagicMock()
    book.user_book_id = user_book_id
    book.title = title
    book.author = author
    book.category = category
    book.cover_image_url = cover_image_url
    book.highlights = highlights or []
    return book


def _parse_sse_events(response_text: str) -> list[dict]:
    """Parse SSE data lines from a response body into a list of dicts."""
    events = []
    for line in response_text.strip().split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSyncDownEndpointSSE:
    """Tests for the POST /api/settings/readwise/sync-down SSE endpoint."""

    async def test_returns_sse_content_type(self, client):
        """Endpoint returns text/event-stream content type."""
        # Patch _create_client to avoid real API calls; return empty iterator
        mock_client = MagicMock()
        mock_client.v2.export_highlights.return_value = iter([])
        mock_client.close = MagicMock()

        with patch(
            "app.services.readwise.ReadwiseService._create_client",
            return_value=mock_client,
        ):
            response = await client.post("/api/settings/readwise/sync-down")
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]

    async def test_response_contains_sse_data_lines(self, client):
        """Response body contains properly formatted SSE data: lines."""
        mock_client = MagicMock()
        mock_client.v2.export_highlights.return_value = iter([])
        mock_client.close = MagicMock()

        with patch(
            "app.services.readwise.ReadwiseService._create_client",
            return_value=mock_client,
        ):
            response = await client.post("/api/settings/readwise/sync-down")
        assert response.status_code == 200
        lines = [
            line for line in response.text.strip().split("\n") if line.strip().startswith("data: ")
        ]
        assert len(lines) >= 1

    async def test_events_are_valid_json(self, client):
        """Each SSE data line is valid JSON."""
        mock_client = MagicMock()
        mock_client.v2.export_highlights.return_value = iter([])
        mock_client.close = MagicMock()

        with patch(
            "app.services.readwise.ReadwiseService._create_client",
            return_value=mock_client,
        ):
            response = await client.post("/api/settings/readwise/sync-down")
        events = _parse_sse_events(response.text)
        assert len(events) >= 1
        for event in events:
            assert "phase" in event
            assert "message" in event


class TestSyncDownUnconfiguredEndpoint:
    """Tests for sync-down when Readwise token is not configured."""

    async def test_unconfigured_returns_error_event(self, client_readwise_unconfigured):
        """With no token configured, returns a complete event with error message.

        The endpoint creates ReadwiseService() directly (not via DI), so we
        create a real ReadwiseService with an empty api_token and patch the
        constructor in the endpoint module to return it.
        """
        # Pass empty string to bypass get_settings() env var lookup
        unconfigured_service = ReadwiseService(api_token="")

        with patch(
            "app.api.settings.ReadwiseService",
            return_value=unconfigured_service,
        ):
            response = await client_readwise_unconfigured.post("/api/settings/readwise/sync-down")

        assert response.status_code == 200
        events = _parse_sse_events(response.text)
        assert len(events) >= 1

        # The last (or only) event should be a "complete" phase with errors
        complete_events = [e for e in events if e["phase"] == "complete"]
        assert len(complete_events) >= 1

        complete = complete_events[-1]
        assert len(complete["errors"]) > 0
        error_text = " ".join(complete["errors"]).lower()
        assert "not configured" in error_text or "token" in error_text


class TestSyncDownSuccessfulEndpoint:
    """Integration tests for successful sync-down through the SSE endpoint."""

    async def test_successful_sync_streams_all_phases(self, client, test_session):
        """Mocked sync-down produces fetching -> processing -> complete SSE events."""
        h1 = _make_export_highlight(id=5001, text="Integration test highlight 1")
        h2 = _make_export_highlight(
            id=5002, text="Integration test highlight 2", note="A test note", location=77
        )
        export_book = _make_export_book(
            user_book_id=500,
            title="Integration Test Book",
            author="Test Author",
            cover_image_url="https://example.com/int-cover.jpg",
            highlights=[h1, h2],
        )

        mock_client = MagicMock()
        mock_client.v2.export_highlights.return_value = iter([export_book])
        mock_client.close = MagicMock()

        with patch(
            "app.services.readwise.ReadwiseService._create_client",
            return_value=mock_client,
        ):
            response = await client.post("/api/settings/readwise/sync-down")

        assert response.status_code == 200
        events = _parse_sse_events(response.text)

        phases = [e["phase"] for e in events]
        assert "fetching" in phases
        assert "processing" in phases
        assert "complete" in phases

        # Complete event should report correct counts
        complete = [e for e in events if e["phase"] == "complete"][-1]
        assert complete["books_processed"] == 1
        assert complete["highlights_imported"] == 2
        assert complete["highlights_skipped"] == 0
        assert complete["errors"] == []

    async def test_successful_sync_persists_books_in_db(self, client, test_session):
        """After successful sync, books are persisted in the database."""
        h1 = _make_export_highlight(id=6001, text="DB persist highlight")
        export_book = _make_export_book(
            user_book_id=600,
            title="DB Persist Test Book",
            author="DB Test Author",
            highlights=[h1],
        )

        mock_client = MagicMock()
        mock_client.v2.export_highlights.return_value = iter([export_book])
        mock_client.close = MagicMock()

        with patch(
            "app.services.readwise.ReadwiseService._create_client",
            return_value=mock_client,
        ):
            response = await client.post("/api/settings/readwise/sync-down")

        assert response.status_code == 200

        # Verify book exists in DB
        result = await test_session.execute(
            select(Book).where(Book.title == "DB Persist Test Book")
        )
        book = result.scalar_one_or_none()
        assert book is not None
        assert book.author == "DB Test Author"

    async def test_successful_sync_persists_highlights_in_db(self, client, test_session):
        """After successful sync, highlights are persisted with correct fields."""
        h1 = _make_export_highlight(
            id=7001,
            text="Highlight for DB check",
            note="DB note",
            location=99,
            highlighted_at=datetime(2024, 8, 1, tzinfo=UTC),
        )
        export_book = _make_export_book(
            user_book_id=700,
            title="Highlight DB Test",
            author="HL Author",
            highlights=[h1],
        )

        mock_client = MagicMock()
        mock_client.v2.export_highlights.return_value = iter([export_book])
        mock_client.close = MagicMock()

        with patch(
            "app.services.readwise.ReadwiseService._create_client",
            return_value=mock_client,
        ):
            response = await client.post("/api/settings/readwise/sync-down")

        assert response.status_code == 200

        # Verify highlight exists in DB
        result = await test_session.execute(
            select(Highlight).where(Highlight.readwise_id == "7001")
        )
        highlight = result.scalar_one_or_none()
        assert highlight is not None
        assert highlight.text == "Highlight for DB check"
        assert highlight.note == "DB note"
        assert highlight.page_number == "99"
        assert highlight.sync_status == SyncStatus.SYNCED
        assert highlight.synced_at is not None

    async def test_multiple_books_sync(self, client, test_session):
        """Sync-down with multiple books creates all expected records."""
        h1 = _make_export_highlight(id=8001, text="Book A highlight")
        h2 = _make_export_highlight(id=8002, text="Book B highlight 1")
        h3 = _make_export_highlight(id=8003, text="Book B highlight 2")

        book_a = _make_export_book(
            user_book_id=800,
            title="Multi-Sync Book A",
            author="Author A",
            highlights=[h1],
        )
        book_b = _make_export_book(
            user_book_id=801,
            title="Multi-Sync Book B",
            author="Author B",
            highlights=[h2, h3],
        )

        mock_client = MagicMock()
        mock_client.v2.export_highlights.return_value = iter([book_a, book_b])
        mock_client.close = MagicMock()

        with patch(
            "app.services.readwise.ReadwiseService._create_client",
            return_value=mock_client,
        ):
            response = await client.post("/api/settings/readwise/sync-down")

        assert response.status_code == 200

        events = _parse_sse_events(response.text)
        complete = [e for e in events if e["phase"] == "complete"][-1]
        assert complete["books_processed"] == 2
        assert complete["highlights_imported"] == 3

        # Verify DB state
        book_result = await test_session.execute(select(Book))
        books = book_result.scalars().all()
        synced_titles = {b.title for b in books}
        assert "Multi-Sync Book A" in synced_titles
        assert "Multi-Sync Book B" in synced_titles


class TestSyncDownErrorSchema:
    """Tests that error events use the correct phase/message schema, not the old success schema."""

    async def test_unconfigured_error_uses_phase_not_success(self, client_readwise_unconfigured):
        """Error event for unconfigured token uses phase/message format, not success/errors."""
        unconfigured_service = ReadwiseService(api_token="")

        with patch("app.api.settings.ReadwiseService", return_value=unconfigured_service):
            response = await client_readwise_unconfigured.post("/api/settings/readwise/sync-down")

        events = _parse_sse_events(response.text)
        for event in events:
            # Every event must have phase and message (the correct schema)
            assert "phase" in event, f"Event missing 'phase': {event}"
            assert "message" in event, f"Event missing 'message': {event}"
            # The old broken schema used "success" — it must NOT be present
            assert "success" not in event, f"Event uses old 'success' schema: {event}"

    async def test_sdk_error_uses_phase_not_success(self, client):
        """When SDK raises during fetch, the error event uses phase/message format."""
        mock_client = MagicMock()
        mock_client.v2.export_highlights.side_effect = ConnectionError("API unreachable")
        mock_client.close = MagicMock()

        with patch(
            "app.services.readwise.ReadwiseService._create_client",
            return_value=mock_client,
        ):
            response = await client.post("/api/settings/readwise/sync-down")

        events = _parse_sse_events(response.text)
        for event in events:
            assert "phase" in event
            assert "message" in event
            assert "success" not in event

        # The error event should be phase="complete" with errors
        error_events = [e for e in events if e.get("errors")]
        assert len(error_events) >= 1
        assert "complete" in [e["phase"] for e in error_events]


class TestSyncDownTokenSource:
    """Tests that sync-down uses the env var token, not the DB-stored token."""

    async def test_endpoint_does_not_query_db_for_token(self, client):
        """The sync-down endpoint should use ReadwiseService() directly (env var),
        not call get_settings_service/get_readwise_token from the DB."""
        mock_client = MagicMock()
        mock_client.v2.export_highlights.return_value = iter([])
        mock_client.close = MagicMock()

        with (
            patch(
                "app.services.readwise.ReadwiseService._create_client",
                return_value=mock_client,
            ),
            patch("app.api.settings.get_settings_service") as mock_get_settings_svc,
        ):
            response = await client.post("/api/settings/readwise/sync-down")

        assert response.status_code == 200
        # The endpoint should NOT call get_settings_service at all for sync-down
        mock_get_settings_svc.assert_not_called()


class TestSyncDownCacheHeaders:
    """Tests for SSE response headers."""

    async def test_no_cache_header(self, client):
        """SSE response includes Cache-Control: no-cache."""
        mock_client = MagicMock()
        mock_client.v2.export_highlights.return_value = iter([])
        mock_client.close = MagicMock()

        with patch(
            "app.services.readwise.ReadwiseService._create_client",
            return_value=mock_client,
        ):
            response = await client.post("/api/settings/readwise/sync-down")
        assert response.headers.get("cache-control") == "no-cache"
