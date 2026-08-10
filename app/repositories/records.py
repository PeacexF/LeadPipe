import hashlib
import json
from dataclasses import asdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SourceRecord
from app.deduplication.fingerprint import fingerprints
from app.domain.models import NormalizedLead
from app.validation.models import LeadValidation


def record_key(lead: NormalizedLead, external_id: str | None) -> str:
    if external_id:
        return external_id
    payload = json.dumps(_lead_payload(lead), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:64]


def _lead_payload(lead: NormalizedLead) -> dict[str, Any]:
    payload = asdict(lead)
    payload.pop("collected_at", None)
    payload.pop("source", None)
    return payload


class SourceRecordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, record_id: int) -> SourceRecord | None:
        return await self.session.get(SourceRecord, record_id)

    async def by_key(self, source_id: int, key: str) -> SourceRecord | None:
        stmt = select(SourceRecord).where(
            SourceRecord.source_id == source_id, SourceRecord.record_key == key
        )
        return (await self.session.scalars(stmt)).first()

    async def upsert(
        self,
        source_id: int,
        lead: NormalizedLead,
        validation: LeadValidation,
        job_id: int | None = None,
        raw: dict[str, Any] | None = None,
        external_id: str | None = None,
    ) -> tuple[SourceRecord, bool]:
        # Returns the record and whether it was seen for the first time
        key = record_key(lead, external_id)
        record = await self.by_key(source_id, key)
        is_new = record is None
        if record is None:
            record = SourceRecord(source_id=source_id, record_key=key)
            self.session.add(record)

        fp = fingerprints(lead)
        record.job_id = job_id
        record.external_id = external_id
        record.source_url = lead.source.url
        record.raw = raw or {}
        record.normalized = _lead_payload(lead)
        record.fp_email = fp.email
        record.fp_domain = fp.domain
        record.fp_phone = fp.phone
        record.fp_name_slug = fp.name_slug
        record.fp_location = fp.location
        record.validation_status = validation.status
        record.validation_fields = {
            name: {"status": result.status.value, "reason": result.reason}
            for name, result in validation.fields.items()
        }
        record.collected_at = lead.collected_at
        await self.session.flush()
        return record, is_new
