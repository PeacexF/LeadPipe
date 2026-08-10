from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.filters import LeadFilter
from app.exports.writers import COLUMNS, write_csv, write_json
from app.repositories.leads import LeadRepository

FORMATS = ("csv", "json")

CONTENT_TYPES = {"csv": "text/csv", "json": "application/json"}


def export_leads(
    session: AsyncSession,
    export_format: str = "csv",
    filters: LeadFilter | None = None,
    batch_size: int = 500,
) -> AsyncIterator[str]:
    if export_format not in FORMATS:
        raise ValueError(f"unsupported export format: {export_format}")
    rows = LeadRepository(session).iter_export(filters, batch_size)
    return write_csv(rows) if export_format == "csv" else write_json(rows)


__all__ = [
    "COLUMNS",
    "CONTENT_TYPES",
    "FORMATS",
    "export_leads",
    "write_csv",
    "write_json",
]
