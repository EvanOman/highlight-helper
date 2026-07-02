"""Unit tests for the CoachingCard model."""

from decimal import Decimal

from app.models.coaching import CoachingCard, CoachingCardStatus, CoachingCardType


class TestCoachingCardType:
    """Tests for CoachingCardType enum."""

    def test_enum_values(self):
        assert CoachingCardType.CROSS_BOOK_CONNECTION.value == "cross_book_connection"
        assert CoachingCardType.COMPREHENSION_CHECK.value == "comprehension_check"
        assert CoachingCardType.SPACED_REVIEW.value == "spaced_review"

    def test_enum_is_string(self):
        assert isinstance(CoachingCardType.CROSS_BOOK_CONNECTION, str)


class TestCoachingCardStatus:
    """Tests for CoachingCardStatus enum."""

    def test_enum_values(self):
        assert CoachingCardStatus.PENDING.value == "pending"
        assert CoachingCardStatus.SHOWN.value == "shown"
        assert CoachingCardStatus.ENGAGED.value == "engaged"
        assert CoachingCardStatus.DISMISSED.value == "dismissed"
        assert CoachingCardStatus.EXPIRED.value == "expired"


class TestCoachingCardModel:
    """Tests for the CoachingCard model."""

    async def test_create_card(self, test_session):
        card = CoachingCard(
            card_type=CoachingCardType.CROSS_BOOK_CONNECTION,
            title="Test Connection",
            body="A fascinating connection between two books.",
            chat_prompt="Help me explore this connection.",
            coaching_system_prompt="You are a reading coach...",
            model="claude-sonnet-4-5-20250929",
            input_tokens=100,
            output_tokens=200,
            cost_usd=Decimal("0.001"),
        )
        test_session.add(card)
        await test_session.flush()

        assert card.id is not None
        assert card.card_type == CoachingCardType.CROSS_BOOK_CONNECTION
        assert card.status == CoachingCardStatus.PENDING
        assert card.title == "Test Connection"
        assert card.created_at is not None

    async def test_card_default_status(self, test_session):
        card = CoachingCard(
            card_type=CoachingCardType.COMPREHENSION_CHECK,
            title="Test",
            body="Test body",
            chat_prompt="Test prompt",
            coaching_system_prompt="Test system prompt",
            model="claude-sonnet-4-5-20250929",
        )
        test_session.add(card)
        await test_session.flush()

        assert card.status == CoachingCardStatus.PENDING

    async def test_card_nullable_fks(self, test_session):
        card = CoachingCard(
            card_type=CoachingCardType.SPACED_REVIEW,
            title="Test",
            body="Test body",
            chat_prompt="Test prompt",
            coaching_system_prompt="Test system prompt",
            model="claude-sonnet-4-5-20250929",
        )
        test_session.add(card)
        await test_session.flush()

        assert card.primary_book_id is None
        assert card.secondary_book_id is None
        assert card.thread_id is None

    async def test_card_with_book_fks(self, test_session, sample_book):
        card = CoachingCard(
            card_type=CoachingCardType.CROSS_BOOK_CONNECTION,
            title="Test",
            body="Test body",
            chat_prompt="Test prompt",
            coaching_system_prompt="Test system prompt",
            model="claude-sonnet-4-5-20250929",
            primary_book_id=sample_book.id,
        )
        test_session.add(card)
        await test_session.flush()

        assert card.primary_book_id == sample_book.id

    async def test_card_repr(self, test_session):
        card = CoachingCard(
            card_type=CoachingCardType.COMPREHENSION_CHECK,
            title="Test",
            body="Test body",
            chat_prompt="Test prompt",
            coaching_system_prompt="Test system prompt",
            model="claude-sonnet-4-5-20250929",
        )
        test_session.add(card)
        await test_session.flush()

        repr_str = repr(card)
        assert "CoachingCard" in repr_str
        assert "comprehension_check" in repr_str
