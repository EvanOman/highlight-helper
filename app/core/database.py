"""Database connection and session management."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=settings.is_development,
)

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
    from sqlalchemy import inspect, text

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
            conn.execute(text("""
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
            """))
            conn.execute(text("""
                INSERT INTO highlights_new
                SELECT id, book_id, text, note, page_number, created_at, type, readwise_id, synced_at, sync_status
                FROM highlights
            """))
            conn.execute(text("DROP TABLE highlights"))
            conn.execute(text("ALTER TABLE highlights_new RENAME TO highlights"))


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
