from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Lead, LeadMerge, Source, SourceRecord
from app.deduplication.fingerprint import Fingerprints, company_slug
from app.deduplication.matcher import DEFAULT_POLICY, MatchPolicy
from app.deduplication.merge import MergedLead
from app.validation.models import LeadValidation


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

    async def link(
        self,
        lead_id: int,
        source_record_id: int,
        rule: str,
        confidence: float,
        needs_review: bool = False,
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
        await self.session.execute(
            update(SourceRecord).where(SourceRecord.id == source_record_id).values(lead_id=lead_id)
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


def _location_key(city: str | None, country: str | None) -> str | None:
    parts = [part for part in (city, country) if part]
    return "|".join(part.casefold() for part in parts) if parts else None
