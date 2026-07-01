"""Coaching service for generating proactive reading engagement cards."""

import json
import logging
import random
from datetime import UTC, datetime, timedelta

import litellm
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.model_registry import calculate_cost, normalize_model_id
from app.models.book import Book
from app.models.coaching import CoachingCardType
from app.models.highlight import Highlight
from app.repositories.coaching import CoachingRepository
from app.services.settings import SettingsService

logger = logging.getLogger(__name__)

CARD_EXPIRY_DAYS = 7
FREQUENCY_CAP_HOURS = 24
SUPPRESSION_THRESHOLD_TOTAL = 3
SUPPRESSION_THRESHOLD_RATE = 0.10

BASE_SYSTEM_PROMPT = """\
You are a reading coach that helps readers engage more deeply with their book highlights. \
You generate thought-provoking coaching cards that prompt reflection and deeper thinking.

You must respond with ONLY a valid JSON object matching the requested schema. Do not include \
any text outside the JSON object. Do not use markdown code fences. Ensure all string values \
are properly escaped for JSON (use \\n for newlines, \\" for quotes within strings)."""

CROSS_BOOK_PROMPT = """\
Generate a coaching card that reveals a genuine conceptual connection between highlights \
from two different books. The connection should be intellectually stimulating — not \
superficial or obvious.

Book 1: "{book1_title}" by {book1_author}
Highlights from Book 1:
{book1_highlights}

Book 2: "{book2_title}" by {book2_author}
Highlights from Book 2:
{book2_highlights}

Respond with JSON:
{{
  "title": "A compelling 5-10 word title for this connection (no quotes around it)",
  "body": "2-3 sentences describing the connection and why it matters. Address the reader directly with 'you'. Make it intriguing enough to spark a conversation.",
  "chat_prompt": "A natural first message the reader would send to start discussing this connection. Write it as if the reader is saying it, e.g. 'I noticed these two books seem to...' or 'Can you help me think about how...'",
  "coaching_system_prompt": "A detailed system prompt for the AI coaching this conversation. Include: the specific highlights being discussed (quoted), why they were selected, instructions to use Socratic questioning, guide the reader to articulate the connection themselves before offering your perspective, push back gently on surface-level answers, and after 2-3 exchanges offer a synthesis."
}}"""

COMPREHENSION_CHECK_PROMPT = """\
Generate a coaching card that asks the reader to apply a concept from their highlights \
to their own experience. Pick the most thought-provoking highlight and craft a question \
that requires genuine reflection, not just recall.

Book: "{book_title}" by {book_author}
Highlights:
{highlights}

Respond with JSON:
{{
  "title": "A compelling 5-10 word title framed as a challenge or question",
  "body": "2-3 sentences that present the core idea from the highlight and challenge the reader to connect it to their life. Address the reader with 'you'.",
  "chat_prompt": "A natural first message the reader would send to start exploring this. Write it as if the reader is saying it, referencing the concept.",
  "coaching_system_prompt": "A detailed system prompt for the AI coaching this conversation. Include: the specific highlight(s) being discussed (quoted), instructions to help the reader apply the concept to their own experience, use follow-up questions like 'Can you think of a specific time when...' or 'How would this change your approach to...', don't accept vague answers, and after 2-3 exchanges offer an insight connecting their experience back to the text."
}}"""

SPACED_REVIEW_PROMPT = """\
Generate a coaching card that resurfaces an older highlight for the reader to revisit. \
The goal is to see if the idea still resonates, if their thinking has evolved, or if \
they can now see it in a new light.

Book: "{book_title}" by {book_author}
Highlight (from {days_ago} days ago):
"{highlight_text}"

Respond with JSON:
{{
  "title": "A compelling 5-10 word title that invites revisiting this idea",
  "body": "2-3 sentences that re-present the highlight and ask whether it still resonates. Address the reader with 'you'. Frame it as an invitation to reflect on how their thinking may have changed.",
  "chat_prompt": "A natural first message the reader would send to start reflecting on this highlight. Write it as if the reader is saying it.",
  "coaching_system_prompt": "A detailed system prompt for the AI coaching this conversation. Include: the specific highlight (quoted), when it was saved, instructions to explore whether the reader's perspective has evolved, ask what originally drew them to highlight this passage, probe whether they've encountered anything since that confirms or challenges this idea, and after 2-3 exchanges help them articulate their current understanding."
}}"""

# Weights for random card type selection
CARD_TYPE_WEIGHTS = {
    CoachingCardType.CROSS_BOOK_CONNECTION: 0.4,
    CoachingCardType.COMPREHENSION_CHECK: 0.35,
    CoachingCardType.SPACED_REVIEW: 0.25,
}


class CoachingService:
    """Service for generating and managing coaching cards."""

    def __init__(self, db: AsyncSession, coaching_model: str | None = None) -> None:
        self.db = db
        self._model_override = normalize_model_id(coaching_model) if coaching_model else None
        self._repo = CoachingRepository(db)
        self._settings = SettingsService(db)

    async def _resolve_model(self) -> str:
        """Model to use: explicit override, else the UI-configured setting."""
        if self._model_override:
            return self._model_override
        return await self._settings.get_coaching_model()

    async def generate_card(
        self,
        card_type: CoachingCardType,
        highlights: list[Highlight],
        books: list[Book],
    ) -> dict | None:
        """Generate a coaching card using the configured coaching model.

        Returns a dict with the card data, or None if generation fails.
        """
        user_prompt = self._build_type_prompt(card_type, highlights, books)
        if not user_prompt:
            return None

        model = await self._resolve_model()
        try:
            response = await litellm.acompletion(
                model=model,
                max_tokens=2048,
                messages=[
                    {"role": "system", "content": BASE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )

            text = response.choices[0].message.content

            if not text:
                logger.error("No text content in coaching card response")
                return None

            # Strip markdown code fences if present
            stripped = text.strip()
            if stripped.startswith("```"):
                lines = stripped.split("\n")
                lines = [ln for ln in lines if not ln.strip().startswith("```")]
                stripped = "\n".join(lines).strip()

            # Find JSON object boundaries
            start = stripped.find("{")
            end = stripped.rfind("}")
            if start != -1 and end != -1:
                stripped = stripped[start : end + 1]

            try:
                card_data = json.loads(stripped)
            except json.JSONDecodeError:
                logger.warning("JSON parse failed, raw text:\n%s", text[:2000])
                return None

            input_tokens = response.usage.prompt_tokens
            output_tokens = response.usage.completion_tokens
            cost = calculate_cost(model, input_tokens, output_tokens)

            card_data["model"] = model
            card_data["input_tokens"] = input_tokens
            card_data["output_tokens"] = output_tokens
            card_data["cost_usd"] = cost

            return card_data

        except Exception:
            logger.exception("Failed to generate coaching card")
            return None

    async def select_and_generate(self) -> dict | None:
        """Select an appropriate card type and generate a card.

        Returns the serialized card dict, or None if conditions prevent generation.
        """
        # 1. Check existing pending card
        existing = await self._repo.get_pending_card()
        if existing:
            return None

        # 2. Frequency cap: last card < 24h ago
        latest = await self._repo.get_latest_card()
        if latest and latest.created_at:
            since = datetime.now(UTC) - latest.created_at.replace(tzinfo=UTC)
            if since < timedelta(hours=FREQUENCY_CAP_HOURS):
                return None

        # 3. Check coaching_enabled setting
        enabled = await self._settings.get_bool("coaching_enabled", default=True)
        if not enabled:
            return None

        # 4. Get engagement rates → filter suppressed types
        rates = await self._repo.get_type_engagement_rates()
        available_types = []
        for ct in CoachingCardType:
            type_stats = rates.get(ct.value)
            if (
                type_stats
                and type_stats["total"] >= SUPPRESSION_THRESHOLD_TOTAL
                and type_stats["rate"] < SUPPRESSION_THRESHOLD_RATE
            ):
                logger.info("Suppressing card type %s (rate: %s)", ct.value, type_stats["rate"])
                continue
            available_types.append(ct)

        if not available_types:
            logger.info("All card types suppressed")
            return None

        # 5. Check library prerequisites
        book_count_result = await self.db.execute(select(func.count(Book.id)))
        book_count = book_count_result.scalar() or 0
        highlight_count_result = await self.db.execute(select(func.count(Highlight.id)))
        highlight_count = highlight_count_result.scalar() or 0

        if book_count == 0 or highlight_count < 3:
            return None

        # Filter types based on library content
        if book_count < 2:
            available_types = [
                t for t in available_types if t != CoachingCardType.CROSS_BOOK_CONNECTION
            ]

        # Check for old highlights for spaced review
        fourteen_days_ago = datetime.now(UTC) - timedelta(days=14)
        old_count_result = await self.db.execute(
            select(func.count(Highlight.id)).where(Highlight.created_at < fourteen_days_ago)
        )
        old_count = old_count_result.scalar() or 0
        if old_count == 0:
            available_types = [t for t in available_types if t != CoachingCardType.SPACED_REVIEW]

        if not available_types:
            return None

        # 6. Weighted random selection
        weights = [CARD_TYPE_WEIGHTS.get(ct, 0.33) for ct in available_types]
        card_type = random.choices(available_types, weights=weights, k=1)[0]

        # 7. Fetch highlights
        highlights, books = await self._fetch_highlights_for_type(card_type)
        if not highlights:
            return None

        # 8. Generate card
        card_data = await self.generate_card(card_type, highlights, books)
        if not card_data:
            return None

        # 9. Save card
        now = datetime.now(UTC)
        highlight_ids = [h.id for h in highlights]
        card = await self._repo.create_card(
            card_type=card_type.value,
            title=card_data["title"],
            body=card_data["body"],
            chat_prompt=card_data["chat_prompt"],
            coaching_system_prompt=card_data["coaching_system_prompt"],
            highlight_ids_json=json.dumps(highlight_ids),
            primary_book_id=books[0].id if books else None,
            secondary_book_id=books[1].id if len(books) > 1 else None,
            model=card_data["model"],
            input_tokens=card_data["input_tokens"],
            output_tokens=card_data["output_tokens"],
            cost_usd=card_data["cost_usd"],
            eligible_after=now + timedelta(hours=FREQUENCY_CAP_HOURS),
            expires_at=now + timedelta(days=CARD_EXPIRY_DAYS),
        )

        return self._serialize_card(card)

    async def _fetch_highlights_for_type(
        self, card_type: CoachingCardType
    ) -> tuple[list[Highlight], list[Book]]:
        """Fetch appropriate highlights for a card type."""
        if card_type == CoachingCardType.CROSS_BOOK_CONNECTION:
            return await self._fetch_cross_book_highlights()
        if card_type == CoachingCardType.COMPREHENSION_CHECK:
            return await self._fetch_comprehension_highlights()
        if card_type == CoachingCardType.SPACED_REVIEW:
            return await self._fetch_spaced_review_highlight()
        return [], []

    async def _fetch_cross_book_highlights(self) -> tuple[list[Highlight], list[Book]]:
        """Fetch highlights from 2 random books with 3+ highlights each."""
        # Find books with 3+ highlights
        result = await self.db.execute(
            select(Book.id)
            .join(Highlight, Highlight.book_id == Book.id)
            .group_by(Book.id)
            .having(func.count(Highlight.id) >= 3)
        )
        eligible_book_ids = [row[0] for row in result.all()]

        if len(eligible_book_ids) < 2:
            return [], []

        chosen_ids = random.sample(eligible_book_ids, 2)

        books_result = await self.db.execute(select(Book).where(Book.id.in_(chosen_ids)))
        books = list(books_result.scalars().all())

        highlights = []
        for book_id in chosen_ids:
            hl_result = await self.db.execute(
                select(Highlight)
                .where(Highlight.book_id == book_id, Highlight.text.isnot(None))
                .order_by(func.random())
                .limit(2)
            )
            highlights.extend(hl_result.scalars().all())

        return highlights, books

    async def _fetch_comprehension_highlights(self) -> tuple[list[Highlight], list[Book]]:
        """Fetch highlights from 1 random book."""
        result = await self.db.execute(
            select(Book.id)
            .join(Highlight, Highlight.book_id == Book.id)
            .where(Highlight.text.isnot(None))
            .group_by(Book.id)
            .having(func.count(Highlight.id) >= 2)
        )
        eligible_book_ids = [row[0] for row in result.all()]

        if not eligible_book_ids:
            return [], []

        book_id = random.choice(eligible_book_ids)
        book_result = await self.db.execute(select(Book).where(Book.id == book_id))
        book = book_result.scalar_one()

        hl_result = await self.db.execute(
            select(Highlight)
            .where(Highlight.book_id == book_id, Highlight.text.isnot(None))
            .order_by(func.random())
            .limit(3)
        )
        highlights = list(hl_result.scalars().all())

        return highlights, [book]

    async def _fetch_spaced_review_highlight(self) -> tuple[list[Highlight], list[Book]]:
        """Fetch 1 highlight from 14+ days ago."""
        fourteen_days_ago = datetime.now(UTC) - timedelta(days=14)

        result = await self.db.execute(
            select(Highlight)
            .where(Highlight.created_at < fourteen_days_ago, Highlight.text.isnot(None))
            .order_by(func.random())
            .limit(1)
        )
        highlight = result.scalar_one_or_none()

        if not highlight:
            return [], []

        book_result = await self.db.execute(select(Book).where(Book.id == highlight.book_id))
        book = book_result.scalar_one()

        return [highlight], [book]

    def _build_type_prompt(
        self,
        card_type: CoachingCardType,
        highlights: list[Highlight],
        books: list[Book],
    ) -> str | None:
        """Build the type-specific user prompt for card generation."""
        if card_type == CoachingCardType.CROSS_BOOK_CONNECTION:
            if len(books) < 2:
                return None
            book1, book2 = books[0], books[1]
            book1_hls = [h for h in highlights if h.book_id == book1.id]
            book2_hls = [h for h in highlights if h.book_id == book2.id]
            return CROSS_BOOK_PROMPT.format(
                book1_title=book1.title,
                book1_author=book1.author,
                book1_highlights="\n".join(f'- "{h.text}"' for h in book1_hls if h.text),
                book2_title=book2.title,
                book2_author=book2.author,
                book2_highlights="\n".join(f'- "{h.text}"' for h in book2_hls if h.text),
            )

        if card_type == CoachingCardType.COMPREHENSION_CHECK:
            if not books:
                return None
            book = books[0]
            return COMPREHENSION_CHECK_PROMPT.format(
                book_title=book.title,
                book_author=book.author,
                highlights="\n".join(f'- "{h.text}"' for h in highlights if h.text),
            )

        if card_type == CoachingCardType.SPACED_REVIEW:
            if not highlights or not books:
                return None
            h = highlights[0]
            book = books[0]
            now = datetime.now(UTC)
            created = h.created_at.replace(tzinfo=UTC) if h.created_at else now
            days_ago = (now - created).days
            return SPACED_REVIEW_PROMPT.format(
                book_title=book.title,
                book_author=book.author,
                highlight_text=h.text,
                days_ago=days_ago,
            )

        return None

    @staticmethod
    def _serialize_card(card) -> dict:
        """Serialize a CoachingCard to a dict for API response."""
        return {
            "id": card.id,
            "card_type": card.card_type,
            "status": card.status,
            "title": card.title,
            "body": card.body,
            "chat_prompt": card.chat_prompt,
            "primary_book_id": card.primary_book_id,
            "secondary_book_id": card.secondary_book_id,
            "created_at": card.created_at.isoformat() if card.created_at else None,
            "expires_at": card.expires_at.isoformat() if card.expires_at else None,
        }
