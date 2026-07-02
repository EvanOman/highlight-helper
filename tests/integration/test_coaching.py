"""Integration tests for coaching card endpoints."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.book import Book
from app.models.chat import ChatThread
from app.models.coaching import CoachingCard, CoachingCardStatus, CoachingCardType
from app.models.highlight import Highlight
from app.models.job import Job
from app.repositories.coaching import CoachingRepository


class TestGetCoachingCard:
    """Tests for GET /api/coaching/card."""

    async def test_returns_null_with_empty_library(self, client: AsyncClient):
        """Test that card endpoint returns null when no books exist."""
        response = await client.get("/api/coaching/card")
        assert response.status_code == 200
        assert response.json() == {"card": None}

    async def test_returns_existing_pending_card(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        """An existing pending card is returned and marked shown."""
        card = CoachingCard(
            card_type=CoachingCardType.COMPREHENSION_CHECK.value,
            status=CoachingCardStatus.PENDING.value,
            title="Existing Card",
            body="Body text",
            chat_prompt="Prompt",
            coaching_system_prompt="System",
            model="claude-sonnet-4-5-20250929",
        )
        test_session.add(card)
        await test_session.flush()

        response = await client.get("/api/coaching/card")
        assert response.status_code == 200
        data = response.json()
        assert data["card"] is not None
        assert data["card"]["title"] == "Existing Card"
        assert data["card"]["status"] == "shown"

    async def test_returns_generating_when_eligible(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        """With enough content, enqueues a job and returns generating status."""
        book = Book(title="Test Book", author="Author")
        test_session.add(book)
        await test_session.flush()

        for i in range(3):
            test_session.add(Highlight(book_id=book.id, text=f"Highlight {i}"))
        await test_session.flush()

        response = await client.get("/api/coaching/card")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "generating"

        # Verify a job was enqueued
        result = await test_session.execute(select(Job).where(Job.kind == "coaching.generate"))
        job = result.scalar_one()
        assert job.status == "queued"

    async def test_returns_generating_when_job_in_flight(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        """When a coaching job is already running, returns generating."""
        job = Job(kind="coaching.generate", payload="{}", status="running")
        test_session.add(job)
        await test_session.flush()

        response = await client.get("/api/coaching/card")
        assert response.status_code == 200
        assert response.json().get("status") == "generating"

    async def test_does_not_double_enqueue(self, client: AsyncClient, test_session: AsyncSession):
        """Calling the endpoint twice doesn't create a second job."""
        book = Book(title="Test Book", author="Author")
        test_session.add(book)
        await test_session.flush()
        for i in range(3):
            test_session.add(Highlight(book_id=book.id, text=f"Highlight {i}"))
        await test_session.flush()

        # First call enqueues
        await client.get("/api/coaching/card")
        # Second call sees the queued job
        response = await client.get("/api/coaching/card")
        assert response.json().get("status") == "generating"

        result = await test_session.execute(select(Job).where(Job.kind == "coaching.generate"))
        assert len(result.scalars().all()) == 1


class TestCoachingCardLifecycle:
    """Tests for the coaching card engage/dismiss lifecycle."""

    async def test_engage_creates_thread(self, client: AsyncClient, test_session: AsyncSession):
        """Test that engaging a card creates a coaching thread and links it."""
        card = CoachingCard(
            card_type=CoachingCardType.COMPREHENSION_CHECK,
            status=CoachingCardStatus.SHOWN,
            title="Test Coaching Card",
            body="Test body text",
            chat_prompt="Help me think about this concept.",
            coaching_system_prompt="You are a reading coach. Ask Socratic questions.",
            model="claude-sonnet-4-5-20250929",
            input_tokens=100,
            output_tokens=200,
            cost_usd=Decimal("0.001"),
        )
        test_session.add(card)
        await test_session.flush()
        await test_session.refresh(card)

        response = await client.post(f"/api/coaching/card/{card.id}/engage")
        assert response.status_code == 200
        data = response.json()
        assert "thread_id" in data
        thread_id = data["thread_id"]

        # Verify thread was created with the coaching prompt
        msg_response = await client.get(f"/api/chat/conversations/{thread_id}")
        assert msg_response.status_code == 200
        messages = msg_response.json()["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Help me think about this concept."

        # Verify card status updated
        await test_session.refresh(card)
        assert card.status == CoachingCardStatus.ENGAGED
        assert card.thread_id == thread_id
        assert card.responded_at is not None

    async def test_dismiss_updates_status(self, client: AsyncClient, test_session: AsyncSession):
        """Test that dismissing a card updates its status."""
        card = CoachingCard(
            card_type=CoachingCardType.SPACED_REVIEW,
            status=CoachingCardStatus.SHOWN,
            title="Dismiss Test",
            body="Body",
            chat_prompt="Prompt",
            coaching_system_prompt="System",
            model="claude-sonnet-4-5-20250929",
        )
        test_session.add(card)
        await test_session.flush()
        await test_session.refresh(card)

        response = await client.post(f"/api/coaching/card/{card.id}/dismiss")
        assert response.status_code == 200
        assert response.json() == {"ok": True}

        await test_session.refresh(card)
        assert card.status == CoachingCardStatus.DISMISSED
        assert card.responded_at is not None

    async def test_engage_nonexistent_card_returns_404(self, client: AsyncClient):
        response = await client.post("/api/coaching/card/99999/engage")
        assert response.status_code == 404

    async def test_dismiss_nonexistent_card_returns_404(self, client: AsyncClient):
        response = await client.post("/api/coaching/card/99999/dismiss")
        assert response.status_code == 404


class TestCoachingStats:
    """Tests for GET /api/coaching/stats."""

    async def test_stats_empty(self, client: AsyncClient):
        """Test stats with no coaching cards."""
        response = await client.get("/api/coaching/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["overall"]["total_cards"] == 0
        assert data["overall"]["engaged"] == 0
        assert data["by_type"] == {}

    async def test_stats_with_cards(self, client: AsyncClient, test_session: AsyncSession):
        """Test stats reflect card statuses correctly."""
        cards = [
            CoachingCard(
                card_type=CoachingCardType.CROSS_BOOK_CONNECTION,
                status=CoachingCardStatus.ENGAGED,
                title="Engaged",
                body="B",
                chat_prompt="P",
                coaching_system_prompt="S",
                model="claude-sonnet-4-5-20250929",
            ),
            CoachingCard(
                card_type=CoachingCardType.CROSS_BOOK_CONNECTION,
                status=CoachingCardStatus.DISMISSED,
                title="Dismissed",
                body="B",
                chat_prompt="P",
                coaching_system_prompt="S",
                model="claude-sonnet-4-5-20250929",
            ),
            CoachingCard(
                card_type=CoachingCardType.COMPREHENSION_CHECK,
                status=CoachingCardStatus.SHOWN,
                title="Shown",
                body="B",
                chat_prompt="P",
                coaching_system_prompt="S",
                model="claude-sonnet-4-5-20250929",
            ),
        ]
        for c in cards:
            test_session.add(c)
        await test_session.flush()

        response = await client.get("/api/coaching/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["overall"]["total_cards"] == 3
        assert data["overall"]["engaged"] == 1
        assert data["overall"]["dismissed"] == 1
        assert data["overall"]["shown"] == 3  # shown + engaged + dismissed all count as "shown"

        by_type = data["by_type"]
        assert "cross_book_connection" in by_type
        assert by_type["cross_book_connection"]["total"] == 2
        assert by_type["cross_book_connection"]["engaged"] == 1


class TestCoachingRepository:
    """Tests for CoachingRepository directly."""

    async def test_get_pending_card_respects_expiry(self, test_session: AsyncSession):
        """Test that expired cards are not returned as pending."""
        repo = CoachingRepository(test_session)

        expired_card = CoachingCard(
            card_type=CoachingCardType.COMPREHENSION_CHECK,
            status=CoachingCardStatus.PENDING,
            title="Expired",
            body="B",
            chat_prompt="P",
            coaching_system_prompt="S",
            model="claude-sonnet-4-5-20250929",
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )
        test_session.add(expired_card)
        await test_session.flush()

        result = await repo.get_pending_card()
        assert result is None

    async def test_get_pending_card_returns_valid(self, test_session: AsyncSession):
        """Test that a valid pending card is returned."""
        repo = CoachingRepository(test_session)

        card = CoachingCard(
            card_type=CoachingCardType.SPACED_REVIEW,
            status=CoachingCardStatus.PENDING,
            title="Valid",
            body="B",
            chat_prompt="P",
            coaching_system_prompt="S",
            model="claude-sonnet-4-5-20250929",
            expires_at=datetime.now(UTC) + timedelta(days=5),
        )
        test_session.add(card)
        await test_session.flush()

        result = await repo.get_pending_card()
        assert result is not None
        assert result.title == "Valid"

    async def test_mark_shown(self, test_session: AsyncSession):
        """Test marking a card as shown."""
        repo = CoachingRepository(test_session)

        card = CoachingCard(
            card_type=CoachingCardType.COMPREHENSION_CHECK,
            title="Test",
            body="B",
            chat_prompt="P",
            coaching_system_prompt="S",
            model="claude-sonnet-4-5-20250929",
        )
        test_session.add(card)
        await test_session.flush()

        updated = await repo.mark_shown(card.id)
        assert updated.status == CoachingCardStatus.SHOWN
        assert updated.shown_at is not None

    async def test_type_engagement_rates(self, test_session: AsyncSession):
        """Test engagement rate calculation per card type."""
        repo = CoachingRepository(test_session)

        # Create 3 cards of same type: 1 engaged, 2 dismissed
        for status in [
            CoachingCardStatus.ENGAGED,
            CoachingCardStatus.DISMISSED,
            CoachingCardStatus.DISMISSED,
        ]:
            card = CoachingCard(
                card_type=CoachingCardType.CROSS_BOOK_CONNECTION,
                status=status,
                title="T",
                body="B",
                chat_prompt="P",
                coaching_system_prompt="S",
                model="claude-sonnet-4-5-20250929",
            )
            test_session.add(card)
        await test_session.flush()

        rates = await repo.get_type_engagement_rates()
        assert "cross_book_connection" in rates
        assert rates["cross_book_connection"]["total"] == 3
        assert rates["cross_book_connection"]["engaged"] == 1
        assert rates["cross_book_connection"]["rate"] == pytest.approx(1 / 3, abs=0.01)

    async def test_create_card_round_trip_storage_format(self, test_session: AsyncSession):
        """Test that enum columns store lowercase values matching pre-enum format.

        Write a card via the repository, then read the raw stored values with
        a raw SQL SELECT to confirm the on-disk format hasn't changed.
        """
        repo = CoachingRepository(test_session)

        card = await repo.create_card(
            card_type=CoachingCardType.CROSS_BOOK_CONNECTION,
            title="Round-trip Test",
            body="Body",
            chat_prompt="Prompt",
            coaching_system_prompt="System",
            model="claude-sonnet-4-5-20250929",
            input_tokens=10,
            output_tokens=20,
            cost_usd=0.001,
        )

        # Verify ORM returns enum members
        assert card.card_type == CoachingCardType.CROSS_BOOK_CONNECTION
        assert card.status == CoachingCardStatus.PENDING

        # Read raw stored values via raw SQL
        raw = await test_session.execute(
            text("SELECT card_type, status FROM coaching_cards WHERE id = :id"),
            {"id": card.id},
        )
        row = raw.one()
        assert row[0] == "cross_book_connection", (
            f"Expected raw card_type 'cross_book_connection', got '{row[0]}'"
        )
        assert row[1] == "pending", f"Expected raw status 'pending', got '{row[1]}'"


class TestThreadDetail:
    """Tests for GET /api/chat/threads/{id}/detail."""

    async def test_detail_returns_coaching_card_fields(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        """Coaching thread detail includes card title and body."""
        card = CoachingCard(
            card_type=CoachingCardType.COMPREHENSION_CHECK,
            status=CoachingCardStatus.ENGAGED,
            title="Deep Dive Title",
            body="Card body with context",
            chat_prompt="Prompt",
            coaching_system_prompt="System",
            model="claude-sonnet-4-5-20250929",
        )
        test_session.add(card)
        await test_session.flush()
        await test_session.refresh(card)

        thread = ChatThread(title="Coaching Thread", coaching_card_id=card.id)
        test_session.add(thread)
        await test_session.flush()
        await test_session.refresh(thread)

        response = await client.get(f"/api/chat/threads/{thread.id}/detail")
        assert response.status_code == 200
        data = response.json()
        assert data["coaching_card_id"] == card.id
        assert data["coaching_card_title"] == "Deep Dive Title"
        assert data["coaching_card_body"] == "Card body with context"
        assert data["title"] == "Coaching Thread"

    async def test_detail_non_coaching_thread_returns_null_fields(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        """Non-coaching thread detail returns null coaching fields."""
        thread = ChatThread(title="Normal Thread")
        test_session.add(thread)
        await test_session.flush()
        await test_session.refresh(thread)

        response = await client.get(f"/api/chat/threads/{thread.id}/detail")
        assert response.status_code == 200
        data = response.json()
        assert data["coaching_card_id"] is None
        assert data["coaching_card_title"] is None
        assert data["coaching_card_body"] is None

    async def test_detail_nonexistent_thread_returns_404(self, client: AsyncClient):
        response = await client.get("/api/chat/threads/99999/detail")
        assert response.status_code == 404


class TestGenerateEndpoint:
    """Tests for POST /api/chat/threads/{id}/generate."""

    async def test_generate_streams_response(self, client: AsyncClient, test_session: AsyncSession):
        """Generate endpoint returns an SSE stream."""
        card = CoachingCard(
            card_type=CoachingCardType.COMPREHENSION_CHECK,
            status=CoachingCardStatus.ENGAGED,
            title="Test",
            body="Body",
            chat_prompt="Think about this",
            coaching_system_prompt="You are a coach.",
            model="claude-sonnet-4-5-20250929",
        )
        test_session.add(card)
        await test_session.flush()
        await test_session.refresh(card)

        thread = ChatThread(title="Test Thread", coaching_card_id=card.id)
        test_session.add(thread)
        await test_session.flush()
        await test_session.refresh(thread)

        from app.models.chat import ChatMessage

        msg = ChatMessage(thread_id=thread.id, role="user", content="Think about this")
        test_session.add(msg)
        await test_session.flush()

        # Mock the chat service to avoid real API calls
        mock_service = MagicMock()

        async def fake_stream(*args, **kwargs):
            yield "Hello from coach"

        mock_service.send_message_from_history = fake_stream
        mock_service.tool_messages = []
        mock_service.last_metrics = None

        from contextlib import asynccontextmanager

        from app.main import app
        from app.services.chat import get_chat_service

        @asynccontextmanager
        async def mock_async_session():
            yield test_session

        app.dependency_overrides[get_chat_service] = lambda: mock_service
        try:
            with patch("app.api.chat.get_async_session", mock_async_session):
                response = await client.post(f"/api/chat/threads/{thread.id}/generate")
        finally:
            del app.dependency_overrides[get_chat_service]

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = response.text
        assert "Hello from coach" in body
        assert "event: done" in body

    async def test_generate_nonexistent_thread_returns_404(self, client: AsyncClient):
        response = await client.post("/api/chat/threads/99999/generate")
        assert response.status_code == 404


class TestCoachingThreadsInGlobalList:
    """Tests for coaching threads appearing in the global thread list."""

    async def test_coaching_thread_appears_in_global_list(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        """Coaching threads (with book_id set) appear in global thread list."""
        from app.models.book import Book

        book = Book(title="Test Book", author="Author")
        test_session.add(book)
        await test_session.flush()
        await test_session.refresh(book)

        card = CoachingCard(
            card_type=CoachingCardType.COMPREHENSION_CHECK,
            status=CoachingCardStatus.ENGAGED,
            title="Card",
            body="B",
            chat_prompt="P",
            coaching_system_prompt="S",
            model="claude-sonnet-4-5-20250929",
            primary_book_id=book.id,
        )
        test_session.add(card)
        await test_session.flush()
        await test_session.refresh(card)

        # Create coaching thread with book_id (simulating engage behavior)
        thread = ChatThread(title="Coaching Thread", book_id=book.id, coaching_card_id=card.id)
        test_session.add(thread)
        await test_session.flush()
        await test_session.refresh(thread)

        # Also create a normal global thread for comparison
        normal_thread = ChatThread(title="Normal Thread")
        test_session.add(normal_thread)
        await test_session.flush()

        # Global list (book_id=None) should include both
        response = await client.get("/api/chat/conversations")
        assert response.status_code == 200
        data = response.json()
        thread_ids = [t["id"] for t in data]
        assert str(thread.id) in thread_ids
        assert str(normal_thread.id) in thread_ids

        # Coaching thread should have coaching_card_id in response
        coaching_entry = next(t for t in data if t["id"] == str(thread.id))
        assert coaching_entry["coaching_card_id"] == card.id
