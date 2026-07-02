"""Database connection and session management."""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import event, inspect
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


def _run_alembic_command(command: str, revision: str = "head") -> None:
    """Run an alembic command synchronously (designed for asyncio.to_thread).

    Args:
        command: "upgrade" or "stamp"
        revision: Target revision (default "head")
    """
    from alembic.config import Config

    from alembic import command as alembic_command

    alembic_cfg = Config()
    alembic_cfg.set_main_option(
        "script_location", str(Path(__file__).resolve().parent.parent.parent / "alembic")
    )
    alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)

    if command == "upgrade":
        alembic_command.upgrade(alembic_cfg, revision)
    elif command == "stamp":
        alembic_command.stamp(alembic_cfg, revision)


def _detect_db_state(conn) -> str:
    """Detect the current state of the database.

    Returns one of:
    - "fresh": No tables exist at all
    - "pre_alembic": Tables exist but no alembic_version table (production case)
    - "alembic": alembic_version table exists
    """
    inspector = inspect(conn)
    table_names = inspector.get_table_names()

    if not table_names:
        return "fresh"
    if "alembic_version" in table_names:
        return "alembic"
    return "pre_alembic"


async def init_db() -> None:
    """Initialize the database using Alembic migrations.

    Handles three scenarios:
    - Fresh DB (no tables): run alembic upgrade head to create everything.
    - Existing DB without alembic_version: stamp baseline (DB already matches),
      then upgrade head for any subsequent migrations.
    - Existing DB with alembic_version: upgrade head.
    """
    # Ensure models are imported so Base.metadata is populated
    import app.models  # noqa: F401

    # Detect DB state using the async engine
    async with engine.connect() as conn:
        db_state = await conn.run_sync(_detect_db_state)

    logger.info(f"Database state detected: {db_state}")

    if db_state == "fresh":
        # Brand new database - run all migrations from scratch
        await asyncio.to_thread(_run_alembic_command, "upgrade", "head")
        logger.info("Database initialized with alembic upgrade head")
    elif db_state == "pre_alembic":
        # Existing database that predates alembic - stamp the baseline
        # then run any migrations added after the baseline
        await asyncio.to_thread(_run_alembic_command, "stamp", "0001")
        logger.info("Existing database stamped at baseline revision 0001")
        await asyncio.to_thread(_run_alembic_command, "upgrade", "head")
        logger.info("Database upgraded to head after baseline stamp")
    else:
        # Database already managed by alembic - just upgrade
        await asyncio.to_thread(_run_alembic_command, "upgrade", "head")
        logger.info("Database upgraded to head")


def create_fts_and_indexes(conn) -> None:
    """Create FTS5 virtual tables, triggers, and indexes.

    This is used by tests that run create_all on in-memory databases and need
    the FTS/index schema that Alembic normally provides. Not used in production
    (Alembic handles it via the baseline migration).
    """
    from sqlalchemy import text

    inspector = inspect(conn)
    table_names = inspector.get_table_names()

    # FTS5 for books
    if "books" in table_names and "books_fts" not in table_names:
        conn.execute(
            text(
                "CREATE VIRTUAL TABLE books_fts USING fts5("
                "title, author, content=books, content_rowid=id)"
            )
        )
        conn.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS books_ai AFTER INSERT ON books BEGIN "
                "INSERT INTO books_fts(rowid, title, author) "
                "VALUES (new.id, new.title, new.author); END"
            )
        )
        conn.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS books_ad AFTER DELETE ON books BEGIN "
                "INSERT INTO books_fts(books_fts, rowid, title, author) "
                "VALUES ('delete', old.id, old.title, old.author); END"
            )
        )
        conn.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS books_au AFTER UPDATE ON books BEGIN "
                "INSERT INTO books_fts(books_fts, rowid, title, author) "
                "VALUES ('delete', old.id, old.title, old.author); "
                "INSERT INTO books_fts(rowid, title, author) "
                "VALUES (new.id, new.title, new.author); END"
            )
        )
        conn.execute(text("INSERT INTO books_fts(books_fts) VALUES('rebuild')"))

    # FTS5 for highlights
    if "highlights" in table_names and "highlights_fts" not in table_names:
        conn.execute(
            text(
                "CREATE VIRTUAL TABLE highlights_fts USING fts5("
                "text, note, content=highlights, content_rowid=id)"
            )
        )
        conn.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS highlights_ai AFTER INSERT ON highlights BEGIN "
                "INSERT INTO highlights_fts(rowid, text, note) "
                "VALUES (new.id, new.text, new.note); END"
            )
        )
        conn.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS highlights_ad AFTER DELETE ON highlights BEGIN "
                "INSERT INTO highlights_fts(highlights_fts, rowid, text, note) "
                "VALUES ('delete', old.id, old.text, old.note); END"
            )
        )
        conn.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS highlights_au AFTER UPDATE ON highlights BEGIN "
                "INSERT INTO highlights_fts(highlights_fts, rowid, text, note) "
                "VALUES ('delete', old.id, old.text, old.note); "
                "INSERT INTO highlights_fts(rowid, text, note) "
                "VALUES (new.id, new.text, new.note); END"
            )
        )
        conn.execute(text("INSERT INTO highlights_fts(highlights_fts) VALUES('rebuild')"))

    # Partial unique index on readwise_id
    if "highlights" in table_names:
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_highlights_readwise_id "
                "ON highlights(readwise_id) WHERE readwise_id IS NOT NULL"
            )
        )


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
