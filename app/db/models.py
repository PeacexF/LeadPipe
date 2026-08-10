from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.validation.models import ValidationStatus


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


def _enum(enum_type: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum_type,
        name=name,
        native_enum=False,
        length=16,
        values_callable=lambda e: [member.value for member in e],
    )


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Source(TimestampMixin, Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


class Lead(TimestampMixin, Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_name: Mapped[str | None] = mapped_column(String(512))
    contact_name: Mapped[str | None] = mapped_column(String(256))
    website: Mapped[str | None] = mapped_column(Text)
    website_domain: Mapped[str | None] = mapped_column(String(255), index=True)
    email: Mapped[str | None] = mapped_column(String(320), index=True)
    phone: Mapped[str | None] = mapped_column(String(32), index=True)
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(128))
    country: Mapped[str | None] = mapped_column(String(64))

    name_slug: Mapped[str | None] = mapped_column(String(512))
    location_key: Mapped[str | None] = mapped_column(String(256), index=True)

    validation_status: Mapped[ValidationStatus] = mapped_column(
        _enum(ValidationStatus, "validation_status"),
        default=ValidationStatus.UNKNOWN,
        nullable=False,
    )
    extra: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    records: Mapped[list[SourceRecord]] = relationship(back_populates="lead")


class CollectionJob(TimestampMixin, Base):
    __tablename__ = "collection_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[JobStatus] = mapped_column(
        _enum(JobStatus, "job_status"), default=JobStatus.PENDING, nullable=False, index=True
    )
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_by: Mapped[str | None] = mapped_column(String(128))

    source: Mapped[Source] = relationship()
    result: Mapped[CollectionJobResult | None] = relationship(back_populates="job")


class CollectionJobResult(Base):
    __tablename__ = "collection_job_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("collection_jobs.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    collected: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    valid: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    invalid: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicates: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    new_leads: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    errors: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    job: Mapped[CollectionJob] = relationship(back_populates="result")


class SourceRecord(Base):
    __tablename__ = "source_records"
    __table_args__ = (UniqueConstraint("source_id", "record_key", name="uq_source_records_key"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("collection_jobs.id", ondelete="SET NULL"), index=True
    )
    lead_id: Mapped[int | None] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), index=True
    )

    record_key: Mapped[str] = mapped_column(String(128), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(128))
    source_url: Mapped[str | None] = mapped_column(Text)

    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    normalized: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    fp_email: Mapped[str | None] = mapped_column(String(320))
    fp_domain: Mapped[str | None] = mapped_column(String(255))
    fp_phone: Mapped[str | None] = mapped_column(String(32))
    fp_name_slug: Mapped[str | None] = mapped_column(String(512))
    fp_location: Mapped[str | None] = mapped_column(String(256))

    validation_status: Mapped[ValidationStatus] = mapped_column(
        _enum(ValidationStatus, "validation_status"),
        default=ValidationStatus.UNKNOWN,
        nullable=False,
    )
    validation_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    lead: Mapped[Lead | None] = relationship(back_populates="records")
    source: Mapped[Source] = relationship()


class LeadMerge(Base):
    __tablename__ = "lead_merges"
    __table_args__ = (UniqueConstraint("lead_id", "source_record_id", name="uq_lead_merges_pair"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    lead_id: Mapped[int] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_record_id: Mapped[int] = mapped_column(
        ForeignKey("source_records.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    merged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
