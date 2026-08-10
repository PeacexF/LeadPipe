"""initial schema

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VALIDATION_STATUS = sa.Enum(
    "valid", "invalid", "unknown", name="validation_status", native_enum=False, length=16
)
JOB_STATUS = sa.Enum(
    "pending",
    "running",
    "completed",
    "failed",
    "cancelled",
    name="job_status",
    native_enum=False,
    length=16,
)


def _ts(name: str) -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("config", JSONB(), nullable=False, server_default="{}"),
        _ts("created_at"),
        _ts("updated_at"),
    )

    op.create_table(
        "leads",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("company_name", sa.String(512)),
        sa.Column("contact_name", sa.String(256)),
        sa.Column("website", sa.Text()),
        sa.Column("website_domain", sa.String(255)),
        sa.Column("email", sa.String(320)),
        sa.Column("phone", sa.String(32)),
        sa.Column("address", sa.Text()),
        sa.Column("city", sa.String(128)),
        sa.Column("country", sa.String(64)),
        sa.Column("name_slug", sa.String(512)),
        sa.Column("location_key", sa.String(256)),
        sa.Column("validation_status", VALIDATION_STATUS, nullable=False, server_default="unknown"),
        sa.Column("metadata", JSONB(), nullable=False, server_default="{}"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("ix_leads_email", "leads", ["email"])
    op.create_index("ix_leads_website_domain", "leads", ["website_domain"])
    op.create_index("ix_leads_phone", "leads", ["phone"])
    op.create_index("ix_leads_location_key", "leads", ["location_key"])
    op.create_index("ix_leads_last_seen_at", "leads", ["last_seen_at"])
    op.create_index("ix_leads_validation_status", "leads", ["validation_status"])
    op.create_index(
        "ix_leads_name_slug_trgm",
        "leads",
        ["name_slug"],
        postgresql_using="gin",
        postgresql_ops={"name_slug": "gin_trgm_ops"},
    )

    op.create_table(
        "collection_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", JOB_STATUS, nullable=False, server_default="pending"),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("ix_collection_jobs_source_id", "collection_jobs", ["source_id"])
    op.create_index("ix_collection_jobs_status", "collection_jobs", ["status"])

    op.create_table(
        "collection_job_results",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "job_id",
            sa.BigInteger(),
            sa.ForeignKey("collection_jobs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("collected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("valid", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invalid", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicates", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_leads", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errors", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "source_records",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id", sa.BigInteger(), sa.ForeignKey("collection_jobs.id", ondelete="SET NULL")
        ),
        sa.Column("lead_id", sa.BigInteger(), sa.ForeignKey("leads.id", ondelete="CASCADE")),
        sa.Column("record_key", sa.String(128), nullable=False),
        sa.Column("external_id", sa.String(128)),
        sa.Column("source_url", sa.Text()),
        sa.Column("raw", JSONB(), nullable=False, server_default="{}"),
        sa.Column("normalized", JSONB(), nullable=False, server_default="{}"),
        sa.Column("fp_email", sa.String(320)),
        sa.Column("fp_domain", sa.String(255)),
        sa.Column("fp_phone", sa.String(32)),
        sa.Column("fp_name_slug", sa.String(512)),
        sa.Column("fp_location", sa.String(256)),
        sa.Column("validation_status", VALIDATION_STATUS, nullable=False, server_default="unknown"),
        sa.Column("validation_fields", JSONB(), nullable=False, server_default="{}"),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        _ts("created_at"),
        sa.UniqueConstraint("source_id", "record_key", name="uq_source_records_key"),
    )
    op.create_index("ix_source_records_source_id", "source_records", ["source_id"])
    op.create_index("ix_source_records_job_id", "source_records", ["job_id"])
    op.create_index("ix_source_records_lead_id", "source_records", ["lead_id"])

    op.create_table(
        "lead_merges",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "lead_id",
            sa.BigInteger(),
            sa.ForeignKey("leads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_record_id",
            sa.BigInteger(),
            sa.ForeignKey("source_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rule", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.false()),
        _ts("merged_at"),
        sa.UniqueConstraint("lead_id", "source_record_id", name="uq_lead_merges_pair"),
    )
    op.create_index("ix_lead_merges_lead_id", "lead_merges", ["lead_id"])
    op.create_index("ix_lead_merges_source_record_id", "lead_merges", ["source_record_id"])


def downgrade() -> None:
    op.drop_table("lead_merges")
    op.drop_table("source_records")
    op.drop_table("collection_job_results")
    op.drop_table("collection_jobs")
    op.drop_table("leads")
    op.drop_table("sources")
