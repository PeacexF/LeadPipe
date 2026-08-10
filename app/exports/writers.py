import csv
import io
import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from app.repositories.leads import LeadExport

COLUMNS = (
    "id",
    "company_name",
    "contact_name",
    "website",
    "email",
    "phone",
    "address",
    "city",
    "country",
    "validation_status",
    "sources",
    "first_seen_at",
    "last_seen_at",
)


async def write_csv(rows: AsyncIterator[LeadExport]) -> AsyncIterator[str]:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(COLUMNS)
    yield _drain(buffer)

    async for row in rows:
        record = _record(row)
        writer.writerow([_cell(record[column]) for column in COLUMNS])
        yield _drain(buffer)


async def write_json(rows: AsyncIterator[LeadExport]) -> AsyncIterator[str]:
    yield "[\n"
    separator = ""
    async for row in rows:
        yield f"{separator}  {json.dumps(_record(row), ensure_ascii=False, default=_json_value)}"
        separator = ",\n"
    yield "\n]\n"


def _record(row: LeadExport) -> dict[str, Any]:
    lead = row.lead
    return {
        "id": lead.id,
        "company_name": lead.company_name,
        "contact_name": lead.contact_name,
        "website": lead.website,
        "email": lead.email,
        "phone": lead.phone,
        "address": lead.address,
        "city": lead.city,
        "country": lead.country,
        "validation_status": lead.validation_status.value,
        "sources": list(row.sources),
        "first_seen_at": lead.first_seen_at,
        "last_seen_at": lead.last_seen_at,
    }


def _json_value(value: Any) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ";".join(str(item) for item in value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _drain(buffer: io.StringIO) -> str:
    value = buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    return value
