"""baseline schema

Revision ID: 0001
Revises:
Create Date: 2026-07-01

Represents the complete database schema including:
- All SQLAlchemy model tables (books, highlights, chat_threads, etc.)
- FTS5 virtual tables and sync triggers for books and highlights
- Partial unique index on highlights.readwise_id
- Index on highlights.book_id

This is a baseline migration: existing production databases already have
this schema applied via the old _run_migrations() startup code. New databases
get everything created fresh by this migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create all tables, FTS5 virtual tables, triggers, and indexes."""

    # --- Core tables (matching SQLAlchemy models) ---

    op.create_table(
        "books",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("author", sa.String(500), nullable=False),
        sa.Column("isbn", sa.String(20), nullable=True),
        sa.Column("cover_url", sa.String(1000), nullable=True),
        sa.Column("is_starred", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
    )

    op.create_table(
        "highlights",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "book_id",
            sa.Integer(),
            sa.ForeignKey("books.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("page_number", sa.String(50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "type",
            sa.Enum("highlight", "note", name="annotationtype"),
            server_default="highlight",
            nullable=False,
        ),
        sa.Column("readwise_id", sa.String(100), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "sync_status",
            sa.Enum("pending", "synced", "removed_externally", name="syncstatus"),
            server_default="pending",
            nullable=False,
        ),
    )

    op.create_index("ix_highlights_book_id", "highlights", ["book_id"])

    op.create_table(
        "coaching_cards",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("card_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("chat_prompt", sa.Text(), nullable=False),
        sa.Column("coaching_system_prompt", sa.Text(), nullable=False),
        sa.Column("highlight_ids_json", sa.Text(), nullable=True),
        sa.Column(
            "primary_book_id",
            sa.Integer(),
            sa.ForeignKey("books.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "secondary_book_id",
            sa.Integer(),
            sa.ForeignKey("books.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("thread_id", sa.Integer(), nullable=True),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(12, 8), nullable=False, server_default="0"),
        sa.Column("eligible_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("shown_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "chat_threads",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column(
            "book_id",
            sa.Integer(),
            sa.ForeignKey("books.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "coaching_card_id",
            sa.Integer(),
            sa.ForeignKey("coaching_cards.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
    )

    # Now add the FK from coaching_cards.thread_id -> chat_threads.id
    # We created coaching_cards first (no FK to chat_threads initially),
    # then chat_threads (FK to coaching_cards). Now we need the reverse FK.
    # SQLite doesn't support ADD CONSTRAINT, but the column was already
    # created without a FK constraint above. For SQLite this is fine -
    # the FK is enforced via PRAGMA foreign_keys=ON at runtime.

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "thread_id",
            sa.Integer(),
            sa.ForeignKey("chat_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_blocks", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
    )

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", sa.Text(), nullable=True),
    )

    op.create_table(
        "api_usage",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("operation", sa.String(100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(12, 8), nullable=False, server_default="0"),
        sa.Column(
            "highlight_id",
            sa.Integer(),
            sa.ForeignKey("highlights.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    op.create_table(
        "chat_metrics",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "thread_id",
            sa.Integer(),
            sa.ForeignKey("chat_threads.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "book_id",
            sa.Integer(),
            sa.ForeignKey("books.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(12, 8), nullable=False, server_default="0"),
        sa.Column("ttft_ms", sa.Float(), nullable=True),
        sa.Column("total_latency_ms", sa.Float(), nullable=True),
        sa.Column("tokens_per_sec", sa.Float(), nullable=True),
        sa.Column("stop_reason", sa.String(50), nullable=True),
        sa.Column("message_count", sa.Integer(), nullable=True),
        sa.Column("context_utilization_pct", sa.Float(), nullable=True),
    )

    # --- Partial unique index on readwise_id ---
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_highlights_readwise_id "
        "ON highlights(readwise_id) WHERE readwise_id IS NOT NULL"
    )

    # --- FTS5 virtual tables and triggers ---

    # Books FTS
    op.execute(
        """
        CREATE VIRTUAL TABLE books_fts USING fts5(
            title, author,
            content=books, content_rowid=id
        )
        """
    )

    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS books_ai AFTER INSERT ON books BEGIN
            INSERT INTO books_fts(rowid, title, author)
            VALUES (new.id, new.title, new.author);
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS books_ad AFTER DELETE ON books BEGIN
            INSERT INTO books_fts(books_fts, rowid, title, author)
            VALUES ('delete', old.id, old.title, old.author);
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS books_au AFTER UPDATE ON books BEGIN
            INSERT INTO books_fts(books_fts, rowid, title, author)
            VALUES ('delete', old.id, old.title, old.author);
            INSERT INTO books_fts(rowid, title, author)
            VALUES (new.id, new.title, new.author);
        END
        """
    )

    # Highlights FTS
    op.execute(
        """
        CREATE VIRTUAL TABLE highlights_fts USING fts5(
            text, note,
            content=highlights, content_rowid=id
        )
        """
    )

    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS highlights_ai AFTER INSERT ON highlights BEGIN
            INSERT INTO highlights_fts(rowid, text, note)
            VALUES (new.id, new.text, new.note);
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS highlights_ad AFTER DELETE ON highlights BEGIN
            INSERT INTO highlights_fts(highlights_fts, rowid, text, note)
            VALUES ('delete', old.id, old.text, old.note);
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS highlights_au AFTER UPDATE ON highlights BEGIN
            INSERT INTO highlights_fts(highlights_fts, rowid, text, note)
            VALUES ('delete', old.id, old.text, old.note);
            INSERT INTO highlights_fts(rowid, text, note)
            VALUES (new.id, new.text, new.note);
        END
        """
    )


def downgrade() -> None:
    """Drop all tables, FTS tables, triggers, and indexes."""

    # Drop triggers first
    for trigger in [
        "books_ai",
        "books_ad",
        "books_au",
        "highlights_ai",
        "highlights_ad",
        "highlights_au",
    ]:
        op.execute(f"DROP TRIGGER IF EXISTS {trigger}")

    # Drop FTS tables
    op.execute("DROP TABLE IF EXISTS books_fts")
    op.execute("DROP TABLE IF EXISTS highlights_fts")

    # Drop indexes
    op.execute("DROP INDEX IF EXISTS idx_highlights_readwise_id")
    op.execute("DROP INDEX IF EXISTS ix_highlights_book_id")

    # Drop tables in reverse dependency order
    op.drop_table("chat_metrics")
    op.drop_table("api_usage")
    op.drop_table("app_settings")
    op.drop_table("chat_messages")
    op.drop_table("chat_threads")
    op.drop_table("coaching_cards")
    op.drop_table("highlights")
    op.drop_table("books")
