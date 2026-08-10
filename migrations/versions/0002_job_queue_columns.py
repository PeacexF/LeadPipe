"""job queue columns

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "collection_jobs",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "collection_jobs",
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
    )
    op.add_column("collection_jobs", sa.Column("heartbeat_at", sa.DateTime(timezone=True)))
    op.add_column("collection_jobs", sa.Column("run_after", sa.DateTime(timezone=True)))
    op.add_column("collection_jobs", sa.Column("claimed_by", sa.String(128)))

    op.create_index(
        "ix_collection_jobs_pending",
        "collection_jobs",
        ["run_after", "created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_collection_jobs_heartbeat",
        "collection_jobs",
        ["heartbeat_at"],
        postgresql_where=sa.text("status = 'running'"),
    )


def downgrade() -> None:
    op.drop_index("ix_collection_jobs_heartbeat", table_name="collection_jobs")
    op.drop_index("ix_collection_jobs_pending", table_name="collection_jobs")
    op.drop_column("collection_jobs", "claimed_by")
    op.drop_column("collection_jobs", "run_after")
    op.drop_column("collection_jobs", "heartbeat_at")
    op.drop_column("collection_jobs", "max_attempts")
    op.drop_column("collection_jobs", "attempts")
