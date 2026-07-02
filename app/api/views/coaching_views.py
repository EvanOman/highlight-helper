"""Coaching card API endpoints."""

import logging

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.coaching import CoachingCardStatus
from app.repositories.chat import ChatRepository, get_chat_repo
from app.repositories.coaching import CoachingRepository, get_coaching_repo
from app.services.coaching import CoachingService

from ._common import router

logger = logging.getLogger(__name__)


@router.get("/api/coaching/card")
async def get_coaching_card(
    coaching_repo: CoachingRepository = Depends(get_coaching_repo),
    db: AsyncSession = Depends(get_db),
):
    """Get or generate a coaching card.

    Returns existing pending card if available, otherwise attempts
    to generate a new one. Returns {"card": null} if no card available.
    """
    # Check for existing pending card
    existing = await coaching_repo.get_pending_card()
    if existing:
        # Mark as shown if still pending
        if existing.status == CoachingCardStatus.PENDING:
            existing = await coaching_repo.mark_shown(existing.id)
        return {"card": CoachingService._serialize_card(existing)}

    # Try to generate a new card
    service = CoachingService(db)
    card_data = await service.select_and_generate()
    if card_data:
        # The card was just created, mark it shown
        await coaching_repo.mark_shown(card_data["id"])
        card_data["status"] = CoachingCardStatus.SHOWN.value
        return {"card": card_data}

    return {"card": None}


@router.post("/api/coaching/card/{card_id}/engage")
async def engage_coaching_card(
    card_id: int,
    coaching_repo: CoachingRepository = Depends(get_coaching_repo),
    chat_repo: ChatRepository = Depends(get_chat_repo),
):
    """Engage with a coaching card — creates a coaching thread.

    Creates a new chat thread linked to the coaching card, saves the
    coaching prompt as the first user message, and returns the thread_id.
    """
    card = await coaching_repo.get_card_or_raise(card_id)

    # Create coaching thread
    thread = await chat_repo.create_thread(
        title=card.title[:200],
        book_id=card.primary_book_id,
    )

    # Set coaching_card_id on the thread
    thread.coaching_card_id = card.id
    await chat_repo.db.flush()

    # Save the coaching prompt as the first user message
    await chat_repo.create_message(
        thread_id=thread.id,
        role="user",
        content=card.chat_prompt,
    )

    # Mark card as engaged
    await coaching_repo.mark_engaged(card_id, thread.id)

    return {"thread_id": thread.id}


@router.post("/api/coaching/card/{card_id}/dismiss")
async def dismiss_coaching_card(
    card_id: int,
    coaching_repo: CoachingRepository = Depends(get_coaching_repo),
):
    """Dismiss a coaching card."""
    await coaching_repo.mark_dismissed(card_id)
    return {"ok": True}


@router.get("/api/coaching/stats")
async def get_coaching_stats(
    coaching_repo: CoachingRepository = Depends(get_coaching_repo),
):
    """Get coaching engagement statistics."""
    stats = await coaching_repo.get_engagement_stats()
    type_rates = await coaching_repo.get_type_engagement_rates()
    return {
        "overall": stats,
        "by_type": type_rates,
    }
