"""Seed a development database with realistic books and highlights.

Usage:
    DATABASE_URL=sqlite+aiosqlite:////tmp/hh_dev.db uv run python scripts/seed_dev_data.py

Never run against the production database — the script refuses to run unless
DATABASE_URL is explicitly set to something other than the default.
"""

import asyncio
import os
import random
import sys
from datetime import UTC, datetime, timedelta
from typing import TypedDict

# Ensure repo root is importable when run as a script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_DB = "sqlite+aiosqlite:///./highlight_helper.db"


class BookSpec(TypedDict):
    title: str
    author: str
    isbn: str
    starred: bool
    highlights: list[tuple[str, str | None, str]]


BOOKS: list[BookSpec] = [
    {
        "title": "Thinking, Fast and Slow",
        "author": "Daniel Kahneman",
        "isbn": "9780374533557",
        "starred": True,
        "highlights": [
            (
                "A reliable way to make people believe in falsehoods is frequent repetition, "
                "because familiarity is not easily distinguished from truth.",
                "Core mechanism behind misinformation",
                "62",
            ),
            (
                "Nothing in life is as important as you think it is, while you are thinking "
                "about it.",
                "The focusing illusion",
                "402",
            ),
            (
                "The confidence that individuals have in their beliefs depends mostly on the "
                "quality of the story they can tell about what they see, even if they see "
                "little.",
                None,
                "87",
            ),
            (
                "We can be blind to the obvious, and we are also blind to our blindness.",
                None,
                "24",
            ),
        ],
    },
    {
        "title": "The Pragmatic Programmer",
        "author": "David Thomas, Andrew Hunt",
        "isbn": "9780135957059",
        "starred": True,
        "highlights": [
            (
                "Don't live with broken windows. Fix each one as soon as it is discovered.",
                "Applies to code quality culture",
                "7",
            ),
            (
                "Every piece of knowledge must have a single, unambiguous, authoritative "
                "representation within a system.",
                "The DRY principle in its original form",
                "31",
            ),
            (
                "Great software today is often preferable to perfect software tomorrow.",
                None,
                "13",
            ),
        ],
    },
    {
        "title": "Meditations",
        "author": "Marcus Aurelius",
        "isbn": "9780812968255",
        "starred": False,
        "highlights": [
            (
                "You have power over your mind — not outside events. Realize this, and you "
                "will find strength.",
                None,
                "47",
            ),
            (
                "Waste no more time arguing about what a good man should be. Be one.",
                "Book X",
                "138",
            ),
            (
                "The impediment to action advances action. What stands in the way becomes the way.",
                "Often quoted as the core of Stoic practice",
                "71",
            ),
        ],
    },
    {
        "title": "Sapiens: A Brief History of Humankind",
        "author": "Yuval Noah Harari",
        "isbn": "9780062316097",
        "starred": False,
        "highlights": [
            (
                "Large numbers of strangers can cooperate successfully by believing in "
                "common myths.",
                "Shared fictions as the foundation of society",
                "27",
            ),
            (
                "We did not domesticate wheat. It domesticated us.",
                None,
                "80",
            ),
            (
                "Money is the most universal and most efficient system of mutual trust "
                "ever devised.",
                None,
                "180",
            ),
            (
                "History is something that very few people have been doing while everyone "
                "else was ploughing fields and carrying water buckets.",
                None,
                "101",
            ),
        ],
    },
    {
        "title": "Deep Work",
        "author": "Cal Newport",
        "isbn": "9781455586691",
        "starred": False,
        "highlights": [
            (
                "The ability to perform deep work is becoming increasingly rare at exactly "
                "the same time it is becoming increasingly valuable in our economy.",
                "The core thesis",
                "14",
            ),
            (
                "Clarity about what matters provides clarity about what does not.",
                None,
                "62",
            ),
        ],
    },
    {
        "title": "The Left Hand of Darkness",
        "author": "Ursula K. Le Guin",
        "isbn": "9780441478125",
        "starred": False,
        "highlights": [
            (
                "It is good to have an end to journey toward; but it is the journey that "
                "matters, in the end.",
                None,
                "220",
            ),
            (
                "To learn which questions are unanswerable, and not to answer them: this "
                "skill is most needful in times of stress and darkness.",
                "Beautiful and practical",
                "153",
            ),
        ],
    },
    {
        "title": "Gödel, Escher, Bach",
        "author": "Douglas Hofstadter",
        "isbn": "9780465026562",
        "starred": False,
        "highlights": [
            (
                "Meaning lies as much in the mind of the reader as in the Haiku.",
                None,
                "162",
            ),
            (
                "Sometimes it seems as though each new step towards AI, rather than "
                "producing something which everyone agrees is real intelligence, merely "
                "reveals what real intelligence is not.",
                "Still true decades later",
                "601",
            ),
        ],
    },
    {
        "title": "The Body Keeps the Score",
        "author": "Bessel van der Kolk",
        "isbn": "9780143127741",
        "starred": False,
        "highlights": [
            (
                "Being able to feel safe with other people is probably the single most "
                "important aspect of mental health.",
                None,
                "81",
            ),
        ],
    },
    {
        "title": "Invisible Cities",
        "author": "Italo Calvino",
        "isbn": "9780156453806",
        "starred": False,
        "highlights": [
            (
                "The city, however, does not tell its past, but contains it like the lines "
                "of a hand.",
                None,
                "11",
            ),
            (
                "Seek and learn to recognize who and what, in the midst of inferno, are not "
                "inferno, then make them endure, give them space.",
                "The famous closing passage",
                "165",
            ),
        ],
    },
    {
        "title": "A Philosophy of Software Design",
        "author": "John Ousterhout",
        "isbn": "9781732102200",
        "starred": False,
        "highlights": [
            (
                "The greatest limitation in writing software is our ability to understand "
                "the systems we are creating.",
                None,
                "1",
            ),
            (
                "Modules should be deep: the best modules are those that provide powerful "
                "functionality yet have simple interfaces.",
                "Deep vs shallow modules",
                "22",
            ),
            (
                "If you're not sure what to call something, it's often a sign that the "
                "design isn't clean.",
                None,
                "121",
            ),
        ],
    },
    {
        "title": "Klara and the Sun",
        "author": "Kazuo Ishiguro",
        "isbn": "9780571364886",
        "starred": False,
        "highlights": [
            (
                "There was something very special, but it wasn't inside Josie. It was inside "
                "those who loved her.",
                None,
                "302",
            ),
        ],
    },
    {
        "title": "The Design of Everyday Things",
        "author": "Don Norman",
        "isbn": "9780465050659",
        "starred": False,
        "highlights": [
            (
                "Good design is actually a lot harder to notice than poor design, in part "
                "because good designs fit our needs so well that the design is invisible.",
                None,
                "xi",
            ),
            (
                "When people have trouble with technology, they blame themselves. This is "
                "backwards: it is the fault of the design.",
                "Learned helplessness in UX",
                "62",
            ),
        ],
    },
]

CHAT_THREADS = [
    ("What are the common themes across my philosophy books?", None),
    ("Summarize what I highlighted in Thinking Fast and Slow", None),
]


async def main() -> None:
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url or db_url == DEFAULT_DB:
        print(
            "Refusing to seed: set DATABASE_URL to a non-production database, e.g.\n"
            "  DATABASE_URL=sqlite+aiosqlite:////tmp/hh_dev.db "
            "uv run python scripts/seed_dev_data.py"
        )
        sys.exit(1)

    # Import after env check so app config picks up DATABASE_URL
    from app.core.database import async_session_maker, init_db
    from app.models.book import Book
    from app.models.chat import ChatMessage, ChatThread
    from app.models.highlight import AnnotationType, Highlight, SyncStatus

    await init_db()

    rng = random.Random(42)
    now = datetime.now(tz=UTC)

    async with async_session_maker() as session:
        for i, spec in enumerate(BOOKS):
            book = Book(
                title=spec["title"],
                author=spec["author"],
                isbn=spec["isbn"],
                cover_url=None,
                is_starred=spec["starred"],
                created_at=now - timedelta(days=len(BOOKS) - i),
            )
            session.add(book)
            await session.flush()

            for j, (text, note, page) in enumerate(spec["highlights"]):
                synced = rng.random() < 0.4
                session.add(
                    Highlight(
                        book_id=book.id,
                        text=text,
                        note=note,
                        page_number=page,
                        type=AnnotationType.HIGHLIGHT,
                        sync_status=SyncStatus.SYNCED if synced else SyncStatus.PENDING,
                        synced_at=(now - timedelta(days=1)) if synced else None,
                        readwise_id=f"rw-{book.id}-{j}" if synced else None,
                        created_at=now - timedelta(days=len(BOOKS) - i, hours=j * 3),
                    )
                )

            # A standalone note on a couple of books
            if i % 4 == 0:
                session.add(
                    Highlight(
                        book_id=book.id,
                        text=None,
                        note="Revisit this chapter — connects to what I read elsewhere.",
                        page_number="ch. 3",
                        type=AnnotationType.NOTE,
                        created_at=now - timedelta(days=len(BOOKS) - i, hours=1),
                    )
                )

        for title, book_id in CHAT_THREADS:
            thread = ChatThread(title=title, book_id=book_id)
            session.add(thread)
            await session.flush()
            session.add_all(
                [
                    ChatMessage(thread_id=thread.id, role="user", content=title),
                    ChatMessage(
                        thread_id=thread.id,
                        role="assistant",
                        content=(
                            "Here are a few threads I noticed across your highlights: "
                            "**attention and focus**, **the limits of self-knowledge**, and "
                            "**systems shaping behavior**. Want me to go deeper on any of "
                            "these?"
                        ),
                    ),
                ]
            )

        await session.commit()

    total_highlights = sum(len(b["highlights"]) for b in BOOKS)
    print(f"Seeded {len(BOOKS)} books, ~{total_highlights} highlights, {len(CHAT_THREADS)} threads")


if __name__ == "__main__":
    asyncio.run(main())
