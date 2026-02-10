"""Search repository for FTS5 full-text search."""

import logging

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db

logger = logging.getLogger(__name__)


class SearchRepository:
    """Repository for full-text search using SQLite FTS5."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def search_books(self, query: str, limit: int = 10) -> list[dict]:
        """Search books by title or author using FTS5 with BM25 ranking.

        Args:
            query: Search query string.
            limit: Maximum number of results to return.

        Returns:
            List of dicts with id, title, author, rank, and snippet.
        """
        if not query or not query.strip():
            return []

        fts_query = self._prepare_fts_query(query)

        result = await self.db.execute(
            text("""
                SELECT
                    b.id,
                    b.title,
                    b.author,
                    books_fts.rank,
                    snippet(books_fts, 0, '**', '**', '...', 32) AS title_snippet,
                    snippet(books_fts, 1, '**', '**', '...', 32) AS author_snippet
                FROM books_fts
                JOIN books b ON b.id = books_fts.rowid
                WHERE books_fts MATCH :query
                ORDER BY books_fts.rank
                LIMIT :limit
            """),
            {"query": fts_query, "limit": limit},
        )

        rows = result.fetchall()
        return [
            {
                "id": row[0],
                "title": row[1],
                "author": row[2],
                "rank": row[3],
                "snippet": row[4] or row[5] or "",
            }
            for row in rows
        ]

    async def search_highlights(self, query: str, limit: int = 10) -> list[dict]:
        """Search highlights by text or note using FTS5 with BM25 ranking.

        Args:
            query: Search query string.
            limit: Maximum number of results to return.

        Returns:
            List of dicts with id, book_id, text, note, book_title,
            book_author, rank, and snippet.
        """
        if not query or not query.strip():
            return []

        fts_query = self._prepare_fts_query(query)

        result = await self.db.execute(
            text("""
                SELECT
                    h.id,
                    h.book_id,
                    h.text,
                    h.note,
                    b.title AS book_title,
                    b.author AS book_author,
                    highlights_fts.rank,
                    snippet(highlights_fts, 0, '**', '**', '...', 64) AS text_snippet,
                    snippet(highlights_fts, 1, '**', '**', '...', 64) AS note_snippet
                FROM highlights_fts
                JOIN highlights h ON h.id = highlights_fts.rowid
                JOIN books b ON b.id = h.book_id
                WHERE highlights_fts MATCH :query
                ORDER BY highlights_fts.rank
                LIMIT :limit
            """),
            {"query": fts_query, "limit": limit},
        )

        rows = result.fetchall()
        return [
            {
                "id": row[0],
                "book_id": row[1],
                "text": row[2],
                "note": row[3],
                "book_title": row[4],
                "book_author": row[5],
                "rank": row[6],
                "snippet": row[7] or row[8] or "",
            }
            for row in rows
        ]

    @staticmethod
    def _prepare_fts_query(query: str) -> str:
        """Prepare a user query for FTS5 MATCH.

        Wraps each word in double quotes to avoid FTS5 syntax errors from
        special characters, and joins with OR for better recall.
        Using OR instead of implicit AND means any matching word will return
        results, which is important for agentic search where the model may
        use broad topic queries like "personal growth self-improvement".
        """
        words = query.strip().split()
        if not words:
            return '""'
        # Quote each token and join with OR for broader matching
        return " OR ".join(f'"{w}"' for w in words)


async def get_search_repo(db: AsyncSession = Depends(get_db)) -> SearchRepository:
    """FastAPI dependency that provides a SearchRepository."""
    return SearchRepository(db)
