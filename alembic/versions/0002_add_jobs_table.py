"""add jobs table

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-01

Adds the ``jobs`` table for the background job queue.  Jobs are claimed by
a single asyncio worker task and dispatched to registered handlers.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the jobs table with indexes on kind and status."""
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(100), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=True),
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

    op.create_index("ix_jobs_kind", "jobs", ["kind"])
    op.create_index("ix_jobs_status", "jobs", ["status"])


def downgrade() -> None:
    """Drop the jobs table and its indexes."""
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_index("ix_jobs_kind", table_name="jobs")
    op.drop_table("jobs")
