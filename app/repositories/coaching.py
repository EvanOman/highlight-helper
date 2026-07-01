"""Repository for coaching card database operations."""

from datetime import UTC, datetime

from fastapi import Depends
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.models.chat import ChatMessage, ChatThread
from app.models.coaching import CoachingCard, CoachingCardStatus


class CoachingRepository:
    """Repository for coaching card CRUD and analytics."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_card(self, **kwargs) -> CoachingCard:
        """Create and persist a coaching card."""
        card = CoachingCard(**kwargs)
        self.db.add(card)
        await self.db.flush()
        await self.db.refresh(card)
        return card

    async def get_card(self, card_id: int) -> CoachingCard | None:
        """Get a card by ID, or None if not found."""
        result = await self.db.execute(select(CoachingCard).where(CoachingCard.id == card_id))
        return result.scalar_one_or_none()

    async def get_card_or_raise(self, card_id: int) -> CoachingCard:
        """Get a card by ID, raising NotFoundError if not found."""
        card = await self.get_card(card_id)
        if not card:
            raise NotFoundError("Coaching card not found")
        return card

    async def get_pending_card(self) -> CoachingCard | None:
        """Get the newest pending/shown card that hasn't expired."""
        now = datetime.now(UTC)
        result = await self.db.execute(
            select(CoachingCard)
            .where(
                CoachingCard.status.in_(
                    [
                        CoachingCardStatus.PENDING.value,
                        CoachingCardStatus.SHOWN.value,
                    ]
                ),
                (CoachingCard.expires_at.is_(None)) | (CoachingCard.expires_at > now),
            )
            .order_by(CoachingCard.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_latest_card(self) -> CoachingCard | None:
        """Get the most recently created card (any status)."""
        result = await self.db.execute(
            select(CoachingCard).order_by(CoachingCard.created_at.desc()).limit(1)
        )
        return result.scalar_one_or_none()

    async def mark_shown(self, card_id: int) -> CoachingCard:
        """Mark a card as shown to the user."""
        card = await self.get_card_or_raise(card_id)
        card.status = CoachingCardStatus.SHOWN.value
        card.shown_at = datetime.now(UTC)
        await self.db.flush()
        await self.db.refresh(card)
        return card

    async def mark_engaged(self, card_id: int, thread_id: int) -> CoachingCard:
        """Mark a card as engaged (user started coaching conversation)."""
        card = await self.get_card_or_raise(card_id)
        card.status = CoachingCardStatus.ENGAGED.value
        card.responded_at = datetime.now(UTC)
        card.thread_id = thread_id
        await self.db.flush()
        await self.db.refresh(card)
        return card

    async def mark_dismissed(self, card_id: int) -> CoachingCard:
        """Mark a card as dismissed by the user."""
        card = await self.get_card_or_raise(card_id)
        card.status = CoachingCardStatus.DISMISSED.value
        card.responded_at = datetime.now(UTC)
        await self.db.flush()
        await self.db.refresh(card)
        return card

    async def get_type_engagement_rates(self) -> dict[str, dict]:
        """Get engagement rates per card type.

        Returns dict like:
        {
            "cross_book_connection": {"total": 10, "engaged": 3, "dismissed": 5, "rate": 0.3},
            ...
        }
        """
        result = await self.db.execute(
            select(
                CoachingCard.card_type,
                func.count(CoachingCard.id).label("total"),
                func.sum(
                    case(
                        (CoachingCard.status == CoachingCardStatus.ENGAGED.value, 1),
                        else_=0,
                    )
                ).label("engaged"),
                func.sum(
                    case(
                        (CoachingCard.status == CoachingCardStatus.DISMISSED.value, 1),
                        else_=0,
                    )
                ).label("dismissed"),
            ).group_by(CoachingCard.card_type)
        )

        rates = {}
        for row in result.all():
            total = row.total or 0
            engaged = row.engaged or 0
            dismissed = row.dismissed or 0
            rate = engaged / total if total > 0 else 0.0
            rates[row.card_type] = {
                "total": total,
                "engaged": engaged,
                "dismissed": dismissed,
                "rate": round(rate, 3),
            }
        return rates

    async def get_engagement_stats(self) -> dict:
        """Get overall coaching engagement statistics."""
        # Card stats
        card_result = await self.db.execute(
            select(
                func.count(CoachingCard.id).label("total_cards"),
                func.sum(
                    case(
                        (CoachingCard.status == CoachingCardStatus.SHOWN.value, 1),
                        (CoachingCard.status == CoachingCardStatus.ENGAGED.value, 1),
                        (CoachingCard.status == CoachingCardStatus.DISMISSED.value, 1),
                        else_=0,
                    )
                ).label("shown"),
                func.sum(
                    case(
                        (CoachingCard.status == CoachingCardStatus.ENGAGED.value, 1),
                        else_=0,
                    )
                ).label("engaged"),
                func.sum(
                    case(
                        (CoachingCard.status == CoachingCardStatus.DISMISSED.value, 1),
                        else_=0,
                    )
                ).label("dismissed"),
                func.coalesce(func.sum(CoachingCard.cost_usd), 0).label("total_generation_cost"),
            )
        )
        card_row = card_result.one()

        total_cards = card_row.total_cards or 0
        shown = card_row.shown or 0
        engaged = card_row.engaged or 0
        dismissed = card_row.dismissed or 0

        # Coaching conversation depth: avg messages per coaching thread
        depth_subq = (
            select(func.count(ChatMessage.id).label("msg_count"))
            .join(ChatThread, ChatMessage.thread_id == ChatThread.id)
            .where(ChatThread.coaching_card_id.isnot(None))
            .group_by(ChatThread.id)
            .subquery()
        )
        avg_depth_result = await self.db.execute(select(func.avg(depth_subq.c.msg_count)))
        avg_depth = avg_depth_result.scalar() or 0

        return {
            "total_cards": total_cards,
            "shown": shown,
            "engaged": engaged,
            "dismissed": dismissed,
            "engagement_rate": round(engaged / shown, 3) if shown > 0 else 0,
            "avg_conversation_depth": round(float(avg_depth), 1),
            "total_generation_cost": float(card_row.total_generation_cost or 0),
        }


async def get_coaching_repo(db: AsyncSession = Depends(get_db)) -> CoachingRepository:
    """Dependency that provides the coaching repository."""
    return CoachingRepository(db)
