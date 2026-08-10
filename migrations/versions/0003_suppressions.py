"""suppression list and retention counters

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SUPPRESSION_KIND = sa.Enum("email", "domain", name="suppression_kind", native_enum=False, length=16)


def upgrade() -> None:
    op.create_table(
        "suppressions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("kind", SUPPRESSION_KIND, nullable=False),
        sa.Column("value", sa.String(320), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("kind", "value", name="uq_suppressions_entry"),
    )
    op.create_index("ix_suppressions_value", "suppressions", ["value"])

    op.add_column(
        "collection_job_results",
        sa.Column("suppressed", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("collection_job_results", "suppressed")
    op.drop_index("ix_suppressions_value", table_name="suppressions")
    op.drop_table("suppressions")
