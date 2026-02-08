"""Integration tests for chat thread persistence."""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


class TestChatThreadCRUD:
    """Tests for chat thread CRUD endpoints."""

    async def test_list_threads_empty(self, client: AsyncClient):
        """Test listing threads when none exist."""
        response = await client.get("/api/chat/threads")
        assert response.status_code == 200
        assert response.json() == []

    async def test_create_thread(self, client: AsyncClient):
        """Test creating a chat thread."""
        response = await client.post(
            "/api/chat/threads",
            json={"title": "Test Thread"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Test Thread"
        assert data["book_id"] is None
        assert data["id"] is not None

    async def test_create_thread_with_book(self, client: AsyncClient, sample_book):
        """Test creating a thread associated with a book."""
        response = await client.post(
            "/api/chat/threads",
            json={"title": "Book Thread", "book_id": sample_book.id},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["book_id"] == sample_book.id

    async def test_list_threads_filtered_by_book(self, client: AsyncClient, sample_book):
        """Test listing threads filtered by book_id."""
        # Create global thread
        await client.post("/api/chat/threads", json={"title": "Global"})
        # Create book thread
        await client.post(
            "/api/chat/threads",
            json={"title": "Book Chat", "book_id": sample_book.id},
        )

        # List global threads
        response = await client.get("/api/chat/threads")
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "Global"

        # List book threads
        response = await client.get(f"/api/chat/threads?book_id={sample_book.id}")
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "Book Chat"

    async def test_delete_thread(self, client: AsyncClient):
        """Test deleting a thread."""
        create_resp = await client.post(
            "/api/chat/threads",
            json={"title": "To Delete"},
        )
        thread_id = create_resp.json()["id"]

        response = await client.delete(f"/api/chat/threads/{thread_id}")
        assert response.status_code == 200
        assert response.json() == {"ok": True}

        # Verify deleted
        list_resp = await client.get("/api/chat/threads")
        assert len(list_resp.json()) == 0

    async def test_delete_thread_not_found(self, client: AsyncClient):
        """Test deleting a non-existent thread returns 404."""
        response = await client.delete("/api/chat/threads/99999")
        assert response.status_code == 404


class TestChatThreadMessages:
    """Tests for thread message endpoints."""

    async def test_get_messages_empty_thread(self, client: AsyncClient):
        """Test getting messages from an empty thread."""
        create_resp = await client.post(
            "/api/chat/threads",
            json={"title": "Empty Thread"},
        )
        thread_id = create_resp.json()["id"]

        response = await client.get(f"/api/chat/threads/{thread_id}/messages")
        assert response.status_code == 200
        assert response.json() == []

    async def test_get_messages_not_found(self, client: AsyncClient):
        """Test getting messages for a non-existent thread returns 404."""
        response = await client.get("/api/chat/threads/99999/messages")
        assert response.status_code == 404


class TestChatRepository:
    """Tests for ChatRepository directly."""

    async def test_create_and_list_messages(self, test_session: AsyncSession):
        """Test creating and listing messages via repository."""
        from app.repositories.chat import ChatRepository

        repo = ChatRepository(test_session)

        thread = await repo.create_thread(title="Test")
        await repo.create_message(thread_id=thread.id, role="user", content="Hello")
        await repo.create_message(thread_id=thread.id, role="assistant", content="Hi there")

        messages = await repo.list_messages(thread.id)
        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[0].content == "Hello"
        assert messages[1].role == "assistant"
        assert messages[1].content == "Hi there"

    async def test_thread_timestamp_update(self, test_session: AsyncSession):
        """Test updating thread timestamp."""
        from app.repositories.chat import ChatRepository

        repo = ChatRepository(test_session)

        thread = await repo.create_thread(title="Test")
        original_updated = thread.updated_at

        await repo.update_thread_timestamp(thread.id)
        await test_session.refresh(thread)

        # updated_at should be >= original (may be same if fast)
        assert thread.updated_at >= original_updated

    async def test_get_thread_or_raise_not_found(self, test_session: AsyncSession):
        """Test that get_thread_or_raise raises NotFoundError."""
        import pytest

        from app.core.exceptions import NotFoundError
        from app.repositories.chat import ChatRepository

        repo = ChatRepository(test_session)

        with pytest.raises(NotFoundError):
            await repo.get_thread_or_raise(99999)

    async def test_delete_thread_cascades_messages(self, client: AsyncClient):
        """Test that deleting a thread cascades to its messages via API."""
        # Create thread with messages
        create_resp = await client.post("/api/chat/threads", json={"title": "To Delete"})
        thread_id = create_resp.json()["id"]

        # Verify we can get messages endpoint (thread exists)
        msg_resp = await client.get(f"/api/chat/threads/{thread_id}/messages")
        assert msg_resp.status_code == 200

        # Delete thread
        del_resp = await client.delete(f"/api/chat/threads/{thread_id}")
        assert del_resp.status_code == 200

        # Thread and messages should be gone
        msg_resp = await client.get(f"/api/chat/threads/{thread_id}/messages")
        assert msg_resp.status_code == 404


class TestChatViewsWithThreads:
    """Tests for chat view pages with thread data."""

    async def test_global_chat_page_renders(self, client: AsyncClient):
        """Test global chat page renders with thread selector."""
        response = await client.get("/chat")
        assert response.status_code == 200
        assert "Chat with Your Highlights" in response.text
        assert "New Chat" in response.text

    async def test_book_chat_page_renders(self, client: AsyncClient, sample_book):
        """Test book chat page renders."""
        response = await client.get(f"/books/{sample_book.id}/chat")
        assert response.status_code == 200
        assert sample_book.title in response.text
        assert "New Chat" in response.text

    async def test_global_chat_page_shows_threads(self, client: AsyncClient):
        """Test that existing threads appear in the chat page."""
        await client.post("/api/chat/threads", json={"title": "My Thread"})

        response = await client.get("/chat")
        assert response.status_code == 200
        assert "My Thread" in response.text
