from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, ScalarSelect, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Lead, LeadMerge, Source, SourceRecord
from app.deduplication.fingerprint import Fingerprints, company_slug
from app.deduplication.matcher import DEFAULT_POLICY, MatchPolicy
from app.deduplication.merge import Candidate, MergedLead
from app.domain.filters import LeadFilter
from app.domain.models import NormalizedLead, SourceRef
from app.validation.models import LeadValidation

_LEAD_KEYS = frozenset(
    {
        "company_name",
        "contact_name",
        "website",
        "website_domain",
        "email",
        "phone",
        "address",
        "city",
        "country",
        "extra",
    }
)


@dataclass(frozen=True, slots=True)
class LeadExport:
    lead: Lead
    sources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Provenance:
    source_name: str
    source_record_id: int
    source_url: str | None
    rule: str
    confidence: float
    needs_review: bool


class LeadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, lead_id: int) -> Lead | None:
        return await self.session.get(Lead, lead_id)

    async def find_candidates(
        self,
        fp: Fingerprints,
        policy: MatchPolicy = DEFAULT_POLICY,
        limit: int = 20,
    ) -> Sequence[Lead]:
        conditions = []
        if fp.email:
            conditions.append(Lead.email == fp.email)
        if fp.domain:
            conditions.append(Lead.website_domain == fp.domain)
        if fp.phone:
            conditions.append(Lead.phone == fp.phone)
        if fp.name_slug and fp.location:
            conditions.append(
                (Lead.location_key == fp.location)
                & (
                    func.similarity(Lead.name_slug, fp.name_slug)
                    >= policy.name_similarity_threshold
                )
            )
        if not conditions:
            return []
        stmt = select(Lead).where(or_(*conditions)).order_by(Lead.id).limit(limit)
        return (await self.session.scalars(stmt)).all()

    async def create(self, merged: MergedLead, validation: LeadValidation) -> Lead:
        lead = Lead(first_seen_at=merged.lead.collected_at)
        self.session.add(lead)
        self._apply(lead, merged, validation)
        await self.session.flush()
        return lead

    async def update(self, lead: Lead, merged: MergedLead, validation: LeadValidation) -> Lead:
        self._apply(lead, merged, validation)
        await self.session.flush()
        return lead

    def _apply(self, lead: Lead, merged: MergedLead, validation: LeadValidation) -> None:
        value = merged.lead
        lead.company_name = value.company_name
        lead.contact_name = value.contact_name
        lead.website = value.website
        lead.website_domain = value.website_domain
        lead.email = value.email
        lead.phone = value.phone
        lead.address = value.address
        lead.city = value.city
        lead.country = value.country
        lead.name_slug = company_slug(value.company_name)
        lead.location_key = _location_key(value.city, value.country)
        lead.validation_status = validation.status
        lead.extra = dict(value.extra)
        lead.last_seen_at = max(lead.first_seen_at, value.collected_at)

    async def page(
        self, filters: LeadFilter | None = None, limit: int = 50, after_id: int = 0
    ) -> list[LeadExport]:
        stmt = (
            select(Lead, _source_names()).where(Lead.id > after_id).order_by(Lead.id).limit(limit)
        )
        for condition in _conditions(filters or LeadFilter()):
            stmt = stmt.where(condition)
        rows = (await self.session.execute(stmt)).all()
        return [LeadExport(lead=lead, sources=tuple(sources or ())) for lead, sources in rows]

    async def iter_export(
        self, filters: LeadFilter | None = None, batch_size: int = 500
    ) -> AsyncIterator[LeadExport]:
        # Keyset-paged so an export never loads the whole table
        after_id = 0
        while True:
            rows = await self.page(filters, batch_size, after_id)
            if not rows:
                return
            for row in rows:
                after_id = row.lead.id
                yield row
            if len(rows) < batch_size:
                return

    async def count(self, filters: LeadFilter | None = None) -> int:
        stmt = select(func.count()).select_from(Lead)
        for condition in _conditions(filters or LeadFilter()):
            stmt = stmt.where(condition)
        return (await self.session.scalars(stmt)).one()

    async def candidates_for(self, lead_id: int) -> list[Candidate]:
        stmt = (
            select(SourceRecord, Source.name, Source.priority)
            .join(Source, Source.id == SourceRecord.source_id)
            .where(SourceRecord.lead_id == lead_id)
            .order_by(SourceRecord.id)
        )
        rows = await self.session.execute(stmt)
        return [
            Candidate(
                lead=_to_normalized(record, source_name),
                origin=str(record.id),
                priority=priority,
            )
            for record, source_name, priority in rows.all()
        ]

    async def link(
        self,
        lead_id: int,
        source_record_id: int,
        rule: str,
        confidence: float,
        needs_review: bool = False,
        claim: bool = True,
    ) -> LeadMerge:
        stmt = select(LeadMerge).where(
            LeadMerge.lead_id == lead_id, LeadMerge.source_record_id == source_record_id
        )
        existing = (await self.session.scalars(stmt)).first()
        if existing is not None:
            existing.rule = rule
            existing.confidence = confidence
            existing.needs_review = needs_review
            await self.session.flush()
            return existing

        merge = LeadMerge(
            lead_id=lead_id,
            source_record_id=source_record_id,
            rule=rule,
            confidence=confidence,
            needs_review=needs_review,
        )
        self.session.add(merge)
        if claim:
            await self.session.execute(
                update(SourceRecord)
                .where(SourceRecord.id == source_record_id)
                .values(lead_id=lead_id)
            )
        await self.session.flush()
        return merge

    async def provenance(self, lead_id: int) -> Sequence[Provenance]:
        stmt = (
            select(
                Source.name,
                SourceRecord.id,
                SourceRecord.source_url,
                LeadMerge.rule,
                LeadMerge.confidence,
                LeadMerge.needs_review,
            )
            .join(SourceRecord, SourceRecord.id == LeadMerge.source_record_id)
            .join(Source, Source.id == SourceRecord.source_id)
            .where(LeadMerge.lead_id == lead_id)
            .order_by(LeadMerge.id)
        )
        rows = await self.session.execute(stmt)
        return [Provenance(*row) for row in rows.all()]


def _source_names() -> ScalarSelect[Any]:
    return (
        select(func.array_agg(func.distinct(Source.name)))
        .select_from(SourceRecord)
        .join(Source, Source.id == SourceRecord.source_id)
        .where(SourceRecord.lead_id == Lead.id)
        .correlate(Lead)
        .scalar_subquery()
    )


def _conditions(filters: LeadFilter) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if filters.country:
        conditions.append(Lead.country == filters.country)
    if filters.city:
        conditions.append(func.lower(Lead.city) == filters.city.lower())
    if filters.validation_status:
        conditions.append(Lead.validation_status == filters.validation_status)
    if filters.created_from:
        conditions.append(Lead.created_at >= filters.created_from)
    if filters.created_to:
        conditions.append(Lead.created_at <= filters.created_to)
    if filters.source:
        conditions.append(
            exists(
                select(SourceRecord.id)
                .join(Source, Source.id == SourceRecord.source_id)
                .where(SourceRecord.lead_id == Lead.id, Source.name == filters.source)
                .correlate(Lead)
            )
        )
    return conditions


def _to_normalized(record: SourceRecord, source_name: str) -> NormalizedLead:
    payload = {key: value for key, value in record.normalized.items() if key in _LEAD_KEYS}
    return NormalizedLead(
        source=SourceRef(name=source_name, url=record.source_url),
        collected_at=record.collected_at,
        **payload,
    )


def _location_key(city: str | None, country: str | None) -> str | None:
    parts = [part for part in (city, country) if part]
    return "|".join(part.casefold() for part in parts) if parts else None
