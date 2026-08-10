from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.db.models import (
    CollectionJob,
    CollectionJobResult,
    JobStatus,
    Lead,
    Source,
    Suppression,
    SuppressionKind,
)
from app.repositories.leads import LeadExport, Provenance
from app.validation import ValidationStatus


class LeadOut(BaseModel):
    id: int
    company_name: str | None
    contact_name: str | None
    website: str | None
    website_domain: str | None
    email: str | None
    phone: str | None
    address: str | None
    city: str | None
    country: str | None
    validation_status: ValidationStatus
    sources: list[str]
    first_seen_at: datetime
    last_seen_at: datetime

    @classmethod
    def of(cls, row: LeadExport) -> LeadOut:
        lead = row.lead
        return cls(
            id=lead.id,
            company_name=lead.company_name,
            contact_name=lead.contact_name,
            website=lead.website,
            website_domain=lead.website_domain,
            email=lead.email,
            phone=lead.phone,
            address=lead.address,
            city=lead.city,
            country=lead.country,
            validation_status=lead.validation_status,
            sources=list(row.sources),
            first_seen_at=lead.first_seen_at,
            last_seen_at=lead.last_seen_at,
        )


class ProvenanceOut(BaseModel):
    source: str
    source_record_id: int
    source_url: str | None
    rule: str
    confidence: float
    needs_review: bool

    @classmethod
    def of(cls, item: Provenance) -> ProvenanceOut:
        return cls(
            source=item.source_name,
            source_record_id=item.source_record_id,
            source_url=item.source_url,
            rule=item.rule,
            confidence=item.confidence,
            needs_review=item.needs_review,
        )


class LeadDetail(LeadOut):
    metadata_: dict[str, Any] = Field(default_factory=dict, alias="metadata")
    provenance: list[ProvenanceOut] = Field(default_factory=list)

    model_config = {"populate_by_name": True}

    @classmethod
    def detail(cls, lead: Lead, sources: tuple[str, ...], items: list[Provenance]) -> LeadDetail:
        base = LeadOut.of(LeadExport(lead=lead, sources=sources)).model_dump()
        return cls(
            **base,
            metadata=dict(lead.extra),
            provenance=[ProvenanceOut.of(item) for item in items],
        )


class Page[T](BaseModel):
    items: list[T]
    limit: int
    next_cursor: int | None = None


class JobResultOut(BaseModel):
    collected: int
    valid: int
    invalid: int
    duplicates: int
    new_leads: int
    errors: int
    suppressed: int

    @classmethod
    def of(cls, result: CollectionJobResult) -> JobResultOut:
        return cls(
            collected=result.collected,
            valid=result.valid,
            invalid=result.invalid,
            duplicates=result.duplicates,
            new_leads=result.new_leads,
            errors=result.errors,
            suppressed=result.suppressed,
        )


class JobOut(BaseModel):
    id: int
    source: str
    status: JobStatus
    attempts: int
    max_attempts: int
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    result: JobResultOut | None = None

    @classmethod
    def of(cls, job: CollectionJob, source: str, result: CollectionJobResult | None) -> JobOut:
        return cls(
            id=job.id,
            source=source,
            status=job.status,
            attempts=job.attempts,
            max_attempts=job.max_attempts,
            error=job.error,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            result=JobResultOut.of(result) if result is not None else None,
        )


class JobCreate(BaseModel):
    source: str = Field(min_length=1, max_length=128)


class SourceOut(BaseModel):
    name: str
    type: str
    priority: int
    enabled: bool

    @classmethod
    def of(cls, source: Source) -> SourceOut:
        return cls(
            name=source.name,
            type=source.type,
            priority=source.priority,
            enabled=source.enabled,
        )


class Health(BaseModel):
    status: str
    version: str


class Ready(BaseModel):
    status: str
    database: bool
    migrations_current: bool
    applied_revision: str | None = None
    expected_revision: str | None = None
    detail: str | None = None


class SuppressionOut(BaseModel):
    id: int
    kind: SuppressionKind
    value: str
    reason: str | None
    created_at: datetime

    @classmethod
    def of(cls, entry: Suppression) -> SuppressionOut:
        return cls(
            id=entry.id,
            kind=entry.kind,
            value=entry.value,
            reason=entry.reason,
            created_at=entry.created_at,
        )


class SuppressionCreate(BaseModel):
    kind: SuppressionKind
    value: str = Field(min_length=1, max_length=320)
    reason: str | None = None


class DeletionResult(BaseModel):
    deleted: bool
    suppressed: list[SuppressionOut] = Field(default_factory=list)
