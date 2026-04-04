"""Integration tests for chat thread persistence."""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.chat import ChatRepository


async def _create_thread(session: AsyncSession, title: str, book_id: int | None = None):
    """Helper to create a thread via the repository."""
    repo = ChatRepository(session)
    thread = await repo.create_thread(title=title, book_id=book_id)
    await session.commit()
    return thread


class TestChatConversationCRUD:
    """Tests for chat conversation (thread) endpoints."""

    async def test_list_conversations_empty(self, client: AsyncClient):
        """Test listing conversations when none exist."""
        response = await client.get("/api/chat/conversations")
        assert response.status_code == 200
        assert response.json() == []

    async def test_list_conversations(self, client: AsyncClient, test_session: AsyncSession):
        """Test listing conversations returns threads with string IDs."""
        thread = await _create_thread(test_session, "Test Thread")

        response = await client.get("/api/chat/conversations")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "Test Thread"
        assert data[0]["id"] == str(thread.id)  # String IDs

    async def test_list_conversations_filtered_by_book(
        self, client: AsyncClient, test_session: AsyncSession, sample_book
    ):
        """Test listing conversations filtered by book_id."""
        await _create_thread(test_session, "Global")
        await _create_thread(test_session, "Book Chat", book_id=sample_book.id)

        # List global threads (no book_id filter returns threads with book_id=None)
        response = await client.get("/api/chat/conversations")
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "Global"

        # List book threads
        response = await client.get(f"/api/chat/conversations?book_id={sample_book.id}")
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "Book Chat"

    async def test_get_conversation_messages(self, client: AsyncClient, test_session: AsyncSession):
        """Test getting messages for a conversation (chatkit format)."""
        thread = await _create_thread(test_session, "Test")
        repo = ChatRepository(test_session)
        await repo.create_message(thread_id=thread.id, role="user", content="Hello")
        await repo.create_message(thread_id=thread.id, role="assistant", content="Hi there")
        await test_session.commit()

        response = await client.get(f"/api/chat/conversations/{thread.id}")
        assert response.status_code == 200
        data = response.json()
        assert "messages" in data
        assert len(data["messages"]) == 2
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][0]["content"] == "Hello"
        assert data["messages"][1]["role"] == "assistant"

    async def test_get_conversation_not_found(self, client: AsyncClient):
        """Test getting a non-existent conversation returns 404."""
        response = await client.get("/api/chat/conversations/99999")
        assert response.status_code == 404

    async def test_delete_conversation(self, client: AsyncClient, test_session: AsyncSession):
        """Test deleting a conversation."""
        thread = await _create_thread(test_session, "To Delete")

        response = await client.delete(f"/api/chat/conversations/{thread.id}")
        assert response.status_code == 200
        assert response.json() == {"ok": True}

        # Verify deleted
        list_resp = await client.get("/api/chat/conversations")
        assert len(list_resp.json()) == 0

    async def test_delete_conversation_not_found(self, client: AsyncClient):
        """Test deleting a non-existent conversation returns 404."""
        response = await client.delete("/api/chat/conversations/99999")
        assert response.status_code == 404

    async def test_delete_conversation_cascades_messages(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        """Test that deleting a conversation cascades to its messages."""
        thread = await _create_thread(test_session, "To Delete")

        # Verify we can get messages (conversation exists)
        msg_resp = await client.get(f"/api/chat/conversations/{thread.id}")
        assert msg_resp.status_code == 200

        # Delete conversation
        del_resp = await client.delete(f"/api/chat/conversations/{thread.id}")
        assert del_resp.status_code == 200

        # Conversation should be gone
        msg_resp = await client.get(f"/api/chat/conversations/{thread.id}")
        assert msg_resp.status_code == 404


class TestChatMessage:
    """Tests for the chat SSE message endpoint."""

    async def test_send_message_with_invalid_book_returns_404(self, client: AsyncClient):
        """Test sending a message with a non-existent book_id returns 404."""
        response = await client.post(
            "/api/chat/chat",
            json={"message": "Hello", "metadata": {"book_id": 99999}},
        )
        assert response.status_code == 404


class TestChatRepository:
    """Tests for ChatRepository directly."""

    async def test_create_and_list_messages(self, test_session: AsyncSession):
        """Test creating and listing messages via repository."""
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
        repo = ChatRepository(test_session)

        thread = await repo.create_thread(title="Test")
        original_updated = thread.updated_at

        await repo.update_thread_timestamp(thread.id)
        await test_session.refresh(thread)

        assert thread.updated_at >= original_updated

    async def test_get_thread_or_raise_not_found(self, test_session: AsyncSession):
        """Test that get_thread_or_raise raises NotFoundError."""
        import pytest

        from app.core.exceptions import NotFoundError

        repo = ChatRepository(test_session)

        with pytest.raises(NotFoundError):
            await repo.get_thread_or_raise(99999)


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

    async def test_global_chat_page_shows_threads(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        """Test that existing threads appear in the chat page."""
        await _create_thread(test_session, "My Thread")

        response = await client.get("/chat")
        assert response.status_code == 200
        assert "My Thread" in response.text
