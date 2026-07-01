"""Unit tests for the CoachingService."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.book import Book
from app.models.coaching import CoachingCard, CoachingCardStatus, CoachingCardType
from app.models.highlight import Highlight
from app.models.settings import AppSetting
from app.services.coaching import CoachingService

COACHING_MODEL = "anthropic/claude-sonnet-4-5-20250929"


class TestGenerateCard:
    """Tests for CoachingService.generate_card()."""

    @patch("app.services.coaching.litellm")
    async def test_generate_card_returns_expected_structure(self, mock_litellm, test_session):
        """Test that generate_card returns card data with all required fields."""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content=json.dumps(
                        {
                            "title": "Unexpected Parallels",
                            "body": "These two books share a surprising insight about human nature.",
                            "chat_prompt": "I noticed both books discuss the nature of habits.",
                            "coaching_system_prompt": "You are a reading coach. Guide the reader through...",
                        }
                    )
                )
            )
        ]
        mock_response.usage.prompt_tokens = 500
        mock_response.usage.completion_tokens = 300
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        service = CoachingService(test_session, coaching_model=COACHING_MODEL)

        book1 = Book(id=1, title="Book A", author="Author A")
        book2 = Book(id=2, title="Book B", author="Author B")
        h1 = MagicMock(spec=Highlight, id=1, book_id=1, text="Highlight 1")
        h2 = MagicMock(spec=Highlight, id=2, book_id=2, text="Highlight 2")

        result = await service.generate_card(
            CoachingCardType.CROSS_BOOK_CONNECTION,
            [h1, h2],
            [book1, book2],
        )

        assert result is not None
        assert result["title"] == "Unexpected Parallels"
        assert result["body"] == "These two books share a surprising insight about human nature."
        assert result["chat_prompt"] == "I noticed both books discuss the nature of habits."
        assert "coaching_system_prompt" in result
        assert result["model"] == COACHING_MODEL
        assert result["input_tokens"] == 500
        assert result["output_tokens"] == 300
        assert result["cost_usd"] > 0

    @patch("app.services.coaching.litellm")
    async def test_generate_card_returns_none_on_api_error(self, mock_litellm, test_session):
        """Test that generate_card returns None when the API call fails."""
        mock_litellm.acompletion = AsyncMock(side_effect=Exception("API error"))

        service = CoachingService(test_session, coaching_model=COACHING_MODEL)

        book = Book(id=1, title="Book", author="Author")
        h = MagicMock(spec=Highlight, id=1, book_id=1, text="Text")

        result = await service.generate_card(
            CoachingCardType.COMPREHENSION_CHECK,
            [h],
            [book],
        )

        assert result is None


class TestSelectAndGenerate:
    """Tests for CoachingService.select_and_generate()."""

    async def test_returns_none_with_empty_library(self, test_session):
        """Test that select_and_generate returns None when library is empty."""
        # Enable coaching
        setting = AppSetting(key="coaching_enabled", value="true")
        test_session.add(setting)
        await test_session.flush()

        service = CoachingService(test_session, coaching_model=COACHING_MODEL)
        result = await service.select_and_generate()
        assert result is None

    async def test_returns_none_when_coaching_disabled(self, test_session):
        """Test that select_and_generate returns None when coaching is disabled."""
        setting = AppSetting(key="coaching_enabled", value="false")
        test_session.add(setting)
        await test_session.flush()

        service = CoachingService(test_session, coaching_model=COACHING_MODEL)
        result = await service.select_and_generate()
        assert result is None

    async def test_returns_none_when_pending_card_exists(self, test_session):
        """Test that select_and_generate returns None if pending card exists."""
        card = CoachingCard(
            card_type=CoachingCardType.COMPREHENSION_CHECK.value,
            status=CoachingCardStatus.PENDING.value,
            title="Existing",
            body="Body",
            chat_prompt="Prompt",
            coaching_system_prompt="System",
            model="claude-sonnet-4-5-20250929",
        )
        test_session.add(card)
        await test_session.flush()

        service = CoachingService(test_session, coaching_model=COACHING_MODEL)
        result = await service.select_and_generate()
        assert result is None

    async def test_frequency_cap_prevents_generation(self, test_session):
        """Test that recent card creation prevents new generation."""
        # Enable coaching
        setting = AppSetting(key="coaching_enabled", value="true")
        test_session.add(setting)
        await test_session.flush()

        # Create a recently dismissed card (within 24h)
        card = CoachingCard(
            card_type=CoachingCardType.COMPREHENSION_CHECK.value,
            status=CoachingCardStatus.DISMISSED.value,
            title="Recent",
            body="Body",
            chat_prompt="Prompt",
            coaching_system_prompt="System",
            model="claude-sonnet-4-5-20250929",
        )
        test_session.add(card)
        await test_session.flush()

        service = CoachingService(test_session, coaching_model=COACHING_MODEL)
        result = await service.select_and_generate()
        assert result is None

    async def test_returns_none_with_too_few_highlights(self, test_session):
        """Test that select_and_generate returns None with < 3 highlights."""
        setting = AppSetting(key="coaching_enabled", value="true")
        test_session.add(setting)

        book = Book(title="Small Book", author="Author")
        test_session.add(book)
        await test_session.flush()

        h = Highlight(book_id=book.id, text="Only one highlight")
        test_session.add(h)
        await test_session.flush()

        service = CoachingService(test_session, coaching_model=COACHING_MODEL)
        result = await service.select_and_generate()
        assert result is None


class TestBuildTypePrompt:
    """Tests for CoachingService._build_type_prompt()."""

    async def test_cross_book_needs_two_books(self, test_session):
        service = CoachingService(test_session, coaching_model=COACHING_MODEL)

        book = Book(id=1, title="Only Book", author="Author")
        h = MagicMock(spec=Highlight, id=1, book_id=1, text="Text")

        result = service._build_type_prompt(
            CoachingCardType.CROSS_BOOK_CONNECTION,
            [h],
            [book],
        )
        assert result is None

    async def test_comprehension_check_builds_prompt(self, test_session):
        service = CoachingService(test_session, coaching_model=COACHING_MODEL)

        book = Book(id=1, title="Test Book", author="Test Author")
        h = MagicMock(spec=Highlight, id=1, book_id=1, text="A great insight")

        result = service._build_type_prompt(
            CoachingCardType.COMPREHENSION_CHECK,
            [h],
            [book],
        )
        assert result is not None
        assert "Test Book" in result
        assert "Test Author" in result
        assert "A great insight" in result

    async def test_spaced_review_builds_prompt(self, test_session):
        service = CoachingService(test_session, coaching_model=COACHING_MODEL)

        book = Book(id=1, title="Old Book", author="Author")
        h = MagicMock(spec=Highlight, id=1, book_id=1, text="An old thought")
        h.created_at = datetime.now(UTC) - timedelta(days=30)

        result = service._build_type_prompt(
            CoachingCardType.SPACED_REVIEW,
            [h],
            [book],
        )
        assert result is not None
        assert "Old Book" in result
        assert "An old thought" in result
        assert "30 days ago" in result
