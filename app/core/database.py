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

    # Check if highlights table exists and needs type column
    if "highlights" in inspector.get_table_names():
        columns = [c["name"] for c in inspector.get_columns("highlights")]
        if "type" not in columns:
            # Add type column with default value 'HIGHLIGHT' (uppercase to match enum)
            conn.execute(
                text("ALTER TABLE highlights ADD COLUMN type VARCHAR(20) DEFAULT 'HIGHLIGHT'")
            )
            # Update existing rows to have the default type
            conn.execute(text("UPDATE highlights SET type = 'HIGHLIGHT' WHERE type IS NULL"))
        else:
            # Fix any lowercase values from previous migration
            conn.execute(text("UPDATE highlights SET type = 'HIGHLIGHT' WHERE type = 'highlight'"))
            conn.execute(text("UPDATE highlights SET type = 'NOTE' WHERE type = 'note'"))


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
