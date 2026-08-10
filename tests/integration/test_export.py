import csv
import io
import json
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import load_config
from app.domain.filters import LeadFilter
from app.exports import export_leads
from app.pipeline import run_collection
from app.repositories import LeadRepository
from app.validation import ValidationStatus

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

CONFIG = Path("examples/configs/csv.yaml")


async def collect_export(session: AsyncSession, fmt: str = "csv", **kwargs: object) -> str:
    filters = LeadFilter(**kwargs)  # type: ignore[arg-type]
    return "".join([chunk async for chunk in export_leads(session, fmt, filters)])


async def test_csv_export_has_one_row_per_lead(session: AsyncSession) -> None:
    stats = await run_collection(session, load_config(CONFIG), "example_csv")
    rows = list(csv.DictReader(io.StringIO(await collect_export(session))))

    assert len(rows) == stats.new_leads
    assert await LeadRepository(session).count() == len(rows)


async def test_json_export_parses_and_carries_provenance(session: AsyncSession) -> None:
    await run_collection(session, load_config(CONFIG), "example_csv")
    leads = json.loads(await collect_export(session, "json"))

    nordic = next(item for item in leads if item["email"] == "info@nordicclean.test")
    assert nordic["sources"] == ["example_csv"]
    assert nordic["phone"] == "+358401234567"
    assert nordic["country"] == "FI"


async def test_filters_narrow_the_export(session: AsyncSession) -> None:
    await run_collection(session, load_config(CONFIG), "example_csv")

    helsinki = list(csv.DictReader(io.StringIO(await collect_export(session, city="Helsinki"))))
    assert helsinki != []
    assert {row["city"] for row in helsinki} == {"Helsinki"}

    invalid = list(
        csv.DictReader(
            io.StringIO(await collect_export(session, validation_status=ValidationStatus.INVALID))
        )
    )
    assert invalid != []
    assert {row["validation_status"] for row in invalid} == {"invalid"}

    by_source = list(
        csv.DictReader(io.StringIO(await collect_export(session, source="example_csv")))
    )
    assert len(by_source) == await LeadRepository(session).count()

    missing = list(csv.DictReader(io.StringIO(await collect_export(session, source="nope"))))
    assert missing == []


async def test_export_is_batched(session: AsyncSession) -> None:
    await run_collection(session, load_config(CONFIG), "example_csv")
    total = await LeadRepository(session).count()

    rows = [row async for row in LeadRepository(session).iter_export(batch_size=2)]
    assert len(rows) == total
    assert [row.lead.id for row in rows] == sorted(row.lead.id for row in rows)


async def test_unknown_format_is_rejected(session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="unsupported export format"):
        await collect_export(session, "xlsx")
