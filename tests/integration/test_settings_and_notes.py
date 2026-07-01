"""Integration tests for settings API/views and note creation."""

from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.services.chat import get_chat_service


class TestSettingsHTMLPage:
    """Tests for GET /settings HTML page."""

    async def test_settings_page_renders(self, client: AsyncClient):
        """Test settings page returns 200 and contains expected sections."""
        response = await client.get("/settings")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        # Readwise section
        assert "Readwise" in response.text
        # Chat model dropdown should be present (rendered via the settings template)
        assert "chat" in response.text.lower() or "model" in response.text.lower()


class TestSettingsAPI:
    """Tests for GET/POST /api/settings."""

    async def test_get_settings_returns_both_models(self, client: AsyncClient):
        """GET /api/settings returns chat_model AND coaching_model."""
        response = await client.get("/api/settings")
        assert response.status_code == 200
        data = response.json()
        assert "chat_model" in data
        assert "coaching_model" in data
        # Both should be non-empty strings
        assert isinstance(data["chat_model"], str) and data["chat_model"]
        assert isinstance(data["coaching_model"], str) and data["coaching_model"]

    async def test_post_settings_update_coaching_model(self, client: AsyncClient):
        """POST /api/settings with valid coaching_model updates it."""
        response = await client.post(
            "/api/settings",
            json={"coaching_model": "anthropic/claude-haiku-4-5-20251001"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["coaching_model"] == "anthropic/claude-haiku-4-5-20251001"

        # Verify it persisted
        get_response = await client.get("/api/settings")
        assert get_response.json()["coaching_model"] == "anthropic/claude-haiku-4-5-20251001"

    async def test_post_settings_invalid_chat_model_returns_422(self, client: AsyncClient):
        """POST /api/settings with invalid chat_model returns 422."""
        response = await client.post(
            "/api/settings",
            json={"chat_model": "gpt-nonsense"},
        )
        assert response.status_code == 422

    async def test_post_settings_bare_model_name_normalizes(self, client: AsyncClient):
        """POST /api/settings with bare model name normalizes to provider-prefixed."""
        response = await client.post(
            "/api/settings",
            json={"chat_model": "claude-opus-4-6"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["chat_model"] == "anthropic/claude-opus-4-6"


class TestAddNotePage:
    """Tests for the add-note page and note creation."""

    async def test_add_note_page_renders(self, client: AsyncClient, sample_book):
        """GET /books/{id}/add-note page renders successfully."""
        response = await client.get(f"/books/{sample_book.id}/add-note")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert sample_book.title in response.text

    async def test_add_note_page_not_found(self, client: AsyncClient):
        """GET /books/99999/add-note returns 404 for missing book."""
        response = await client.get("/books/99999/add-note")
        assert response.status_code == 404

    async def test_create_note_redirects(self, client: AsyncClient, sample_book):
        """POST /books/{id}/notes/create creates a note and redirects (303)."""
        response = await client.post(
            f"/books/{sample_book.id}/notes/create",
            data={
                "note": "A standalone test note about chapter 3",
                "page_number": "33",
                "text": "",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert f"/books/{sample_book.id}" in response.headers["location"]

    async def test_created_note_appears_in_book_detail(self, client: AsyncClient, sample_book):
        """After creating a note, it appears on the book detail page."""
        # Create the note
        await client.post(
            f"/books/{sample_book.id}/notes/create",
            data={
                "note": "Integration test note content",
                "page_number": "77",
                "text": "",
            },
            follow_redirects=False,
        )

        # Check it appears in the book detail
        detail = await client.get(f"/books/{sample_book.id}")
        assert detail.status_code == 200
        assert "Integration test note content" in detail.text


class TestChatSSEStreaming:
    """Tests for chat SSE streaming happy path with a mocked LLM."""

    async def test_chat_sse_stream_happy_path(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        """POST /api/chat/chat with mocked litellm yields init/text/done events."""
        mock_service = MagicMock()

        async def fake_stream(*args, **kwargs):
            yield "Hello, "
            yield "world!"

        mock_service.send_message_from_history = fake_stream
        mock_service.tool_messages = []
        mock_service.last_metrics = None

        @asynccontextmanager
        async def mock_async_session():
            yield test_session

        app.dependency_overrides[get_chat_service] = lambda: mock_service
        try:
            with patch("app.api.chat.get_async_session", mock_async_session):
                response = await client.post(
                    "/api/chat/chat",
                    json={"message": "Hi there"},
                )
        finally:
            del app.dependency_overrides[get_chat_service]

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

        body = response.text
        # Verify SSE protocol events
        assert "event: init" in body
        assert "event: text" in body
        assert "event: done" in body
        # Verify actual text content is present
        assert "Hello, " in body
        assert "world!" in body

    async def test_chat_sse_creates_thread_on_first_message(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        """A chat message without thread_id creates a new thread."""
        mock_service = MagicMock()

        async def fake_stream(*args, **kwargs):
            yield "Response text"

        mock_service.send_message_from_history = fake_stream
        mock_service.tool_messages = []
        mock_service.last_metrics = None

        @asynccontextmanager
        async def mock_async_session():
            yield test_session

        app.dependency_overrides[get_chat_service] = lambda: mock_service
        try:
            with patch("app.api.chat.get_async_session", mock_async_session):
                response = await client.post(
                    "/api/chat/chat",
                    json={"message": "First message"},
                )
        finally:
            del app.dependency_overrides[get_chat_service]

        assert response.status_code == 200
        body = response.text

        # The init event should contain a thread_id
        assert "event: init" in body
        # Parse the thread_id from the init event data line
        for line in body.split("\n"):
            if line.startswith("data:") and "thread_id" in line:
                import json

                data = json.loads(line[len("data:") :].strip())
                assert "thread_id" in data
                thread_id = data["thread_id"]
                assert thread_id  # non-empty
                break
        else:
            raise AssertionError("No init event with thread_id found in SSE stream")
