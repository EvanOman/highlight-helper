"""Database connection and session management."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=settings.is_development,
)


def _configure_sqlite_pragmas(dbapi_connection, connection_record):
    """Configure SQLite pragmas for durability and performance.

    These settings improve crash recovery and concurrent access:
    - journal_mode=WAL: Write-Ahead Logging for better crash recovery
    - synchronous=NORMAL: Good durability with WAL mode
    - busy_timeout=5000: Wait 5 seconds on locks before failing
    """
    cursor = dbapi_connection.cursor()

    # Enable WAL mode for better crash recovery and concurrent reads
    cursor.execute("PRAGMA journal_mode=WAL")
    result = cursor.fetchone()
    if result and result[0].lower() != "wal":
        logger.warning(
            f"Failed to enable WAL mode, journal_mode is: {result[0]}. "
            "This may indicate the database is in use or a permission issue."
        )
    else:
        logger.debug("SQLite WAL mode enabled successfully")

    # NORMAL synchronous is safe with WAL and provides good performance
    cursor.execute("PRAGMA synchronous=NORMAL")

    # Wait 5 seconds on locks before failing
    cursor.execute("PRAGMA busy_timeout=5000")

    # Enforce foreign key constraints (required for ON DELETE CASCADE)
    cursor.execute("PRAGMA foreign_keys=ON")
    logger.debug("SQLite foreign key enforcement enabled")

    cursor.close()


# Register the pragma configuration for SQLite connections
if "sqlite" in settings.database_url:
    event.listen(engine.sync_engine, "connect", _configure_sqlite_pragmas)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that provides a database session."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Initialize the database, creating all tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Run migrations for schema changes
        await conn.run_sync(_run_migrations)


def _run_migrations(conn) -> None:
    """Run database migrations for schema changes."""
    from sqlalchemy import inspect

    inspector = inspect(conn)

    # Check if highlights table exists and needs migrations
    if "highlights" in inspector.get_table_names():
        columns = {c["name"]: c for c in inspector.get_columns("highlights")}

        # Migration 1: Add type column if missing
        if "type" not in columns:
            conn.execute(
                text("ALTER TABLE highlights ADD COLUMN type VARCHAR(20) DEFAULT 'HIGHLIGHT'")
            )
            conn.execute(text("UPDATE highlights SET type = 'HIGHLIGHT' WHERE type IS NULL"))
        else:
            # Fix any lowercase values from previous migration
            conn.execute(text("UPDATE highlights SET type = 'HIGHLIGHT' WHERE type = 'highlight'"))
            conn.execute(text("UPDATE highlights SET type = 'NOTE' WHERE type = 'note'"))

        # Migration 2: Make text column nullable (SQLite workaround - recreate table)
        # SQLite doesn't support ALTER COLUMN, so we need to recreate the table
        # Check if text column is nullable by trying to insert NULL
        text_col = columns.get("text", {})
        if text_col and text_col.get("nullable") is False:
            # SQLite workaround: create new table, copy data, drop old, rename
            conn.execute(
                text("""
                CREATE TABLE IF NOT EXISTS highlights_new (
                    id INTEGER PRIMARY KEY,
                    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
                    text TEXT,
                    note TEXT,
                    page_number VARCHAR(50),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    type VARCHAR(20) DEFAULT 'HIGHLIGHT',
                    readwise_id VARCHAR(255),
                    synced_at TIMESTAMP,
                    sync_status VARCHAR(20) DEFAULT 'PENDING'
                )
            """)
            )
            conn.execute(
                text("""
                INSERT INTO highlights_new
                SELECT id, book_id, text, note, page_number, created_at, type, readwise_id, synced_at, sync_status
                FROM highlights
            """)
            )
            conn.execute(text("DROP TABLE highlights"))
            conn.execute(text("ALTER TABLE highlights_new RENAME TO highlights"))

        # Migration 3: Add unique index on readwise_id (for sync-down deduplication)
        # SQLite supports partial indexes with WHERE clause
        conn.execute(
            text("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_highlights_readwise_id
            ON highlights(readwise_id) WHERE readwise_id IS NOT NULL
        """)
        )

    # Migration 4: Add is_starred column to books table
    if "books" in inspector.get_table_names():
        book_columns = {c["name"]: c for c in inspector.get_columns("books")}
        if "is_starred" not in book_columns:
            conn.execute(text("ALTER TABLE books ADD COLUMN is_starred BOOLEAN NOT NULL DEFAULT 0"))

    # Migration 5: FTS5 full-text search tables for books and highlights
    table_names = inspector.get_table_names()

    if "books" in table_names and "books_fts" not in table_names:
        # Create FTS5 virtual table for books
        conn.execute(
            text("""
            CREATE VIRTUAL TABLE books_fts USING fts5(
                title, author,
                content=books, content_rowid=id
            )
        """)
        )

        # Triggers to keep books_fts in sync
        conn.execute(
            text("""
            CREATE TRIGGER IF NOT EXISTS books_ai AFTER INSERT ON books BEGIN
                INSERT INTO books_fts(rowid, title, author)
                VALUES (new.id, new.title, new.author);
            END
        """)
        )
        conn.execute(
            text("""
            CREATE TRIGGER IF NOT EXISTS books_ad AFTER DELETE ON books BEGIN
                INSERT INTO books_fts(books_fts, rowid, title, author)
                VALUES ('delete', old.id, old.title, old.author);
            END
        """)
        )
        conn.execute(
            text("""
            CREATE TRIGGER IF NOT EXISTS books_au AFTER UPDATE ON books BEGIN
                INSERT INTO books_fts(books_fts, rowid, title, author)
                VALUES ('delete', old.id, old.title, old.author);
                INSERT INTO books_fts(rowid, title, author)
                VALUES (new.id, new.title, new.author);
            END
        """)
        )

        # Populate FTS from existing data
        conn.execute(text("INSERT INTO books_fts(books_fts) VALUES('rebuild')"))

    if "highlights" in table_names and "highlights_fts" not in table_names:
        # Create FTS5 virtual table for highlights
        conn.execute(
            text("""
            CREATE VIRTUAL TABLE highlights_fts USING fts5(
                text, note,
                content=highlights, content_rowid=id
            )
        """)
        )

        # Triggers to keep highlights_fts in sync
        conn.execute(
            text("""
            CREATE TRIGGER IF NOT EXISTS highlights_ai AFTER INSERT ON highlights BEGIN
                INSERT INTO highlights_fts(rowid, text, note)
                VALUES (new.id, new.text, new.note);
            END
        """)
        )
        conn.execute(
            text("""
            CREATE TRIGGER IF NOT EXISTS highlights_ad AFTER DELETE ON highlights BEGIN
                INSERT INTO highlights_fts(highlights_fts, rowid, text, note)
                VALUES ('delete', old.id, old.text, old.note);
            END
        """)
        )
        conn.execute(
            text("""
            CREATE TRIGGER IF NOT EXISTS highlights_au AFTER UPDATE ON highlights BEGIN
                INSERT INTO highlights_fts(highlights_fts, rowid, text, note)
                VALUES ('delete', old.id, old.text, old.note);
                INSERT INTO highlights_fts(rowid, text, note)
                VALUES (new.id, new.text, new.note);
            END
        """)
        )

        # Populate FTS from existing data
        conn.execute(text("INSERT INTO highlights_fts(highlights_fts) VALUES('rebuild')"))

    # Migration 6: Add index on highlights.book_id for efficient book detail queries
    if "highlights" in table_names:
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_highlights_book_id ON highlights (book_id)")
        )

    # Migration 7: Add content_blocks column to chat_messages table
    if "chat_messages" in table_names:
        chat_msg_columns = {c["name"]: c for c in inspector.get_columns("chat_messages")}
        if "content_blocks" not in chat_msg_columns:
            conn.execute(text("ALTER TABLE chat_messages ADD COLUMN content_blocks TEXT"))


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Get a database session for use in background tasks.

    Unlike get_db(), this is a context manager that can be used outside
    of FastAPI's dependency injection system.
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
