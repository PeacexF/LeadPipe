import csv
import io
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest

from app.db.models import Lead
from app.exports import COLUMNS, write_csv, write_json
from app.repositories.leads import LeadExport
from app.validation import ValidationStatus

SEEN = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)


def make_row(lead_id: int, name: str = "Example Oy", sources: tuple[str, ...] = ("csv",)):  # type: ignore[no-untyped-def]
    lead = Lead(
        id=lead_id,
        company_name=name,
        email="contact@example.com",
        phone="+358401234567",
        city="Helsinki",
        country="FI",
        validation_status=ValidationStatus.VALID,
        first_seen_at=SEEN,
        last_seen_at=SEEN,
    )
    return LeadExport(lead=lead, sources=sources)


async def rows(*items: LeadExport) -> AsyncIterator[LeadExport]:
    for item in items:
        yield item


async def collect(chunks: AsyncIterator[str]) -> str:
    return "".join([chunk async for chunk in chunks])


async def test_csv_has_a_header_and_one_row_per_lead() -> None:
    output = await collect(write_csv(rows(make_row(1), make_row(2, "Other Oy"))))
    parsed = list(csv.reader(io.StringIO(output)))

    assert parsed[0] == list(COLUMNS)
    assert len(parsed) == 3
    assert parsed[1][1] == "Example Oy"


async def test_csv_renders_none_as_empty_and_joins_sources() -> None:
    output = await collect(write_csv(rows(make_row(1, sources=("csv", "api")))))
    row = next(iter(csv.DictReader(io.StringIO(output))))

    assert row["sources"] == "csv;api"
    assert row["contact_name"] == ""
    assert row["first_seen_at"] == SEEN.isoformat()


async def test_csv_of_no_leads_is_just_the_header() -> None:
    output = await collect(write_csv(rows()))
    assert output.strip() == ",".join(COLUMNS)


async def test_json_is_a_valid_array() -> None:
    output = await collect(write_json(rows(make_row(1), make_row(2, "Other Oy"))))
    parsed = json.loads(output)

    assert [item["company_name"] for item in parsed] == ["Example Oy", "Other Oy"]
    assert parsed[0]["sources"] == ["csv"]
    assert parsed[0]["validation_status"] == "valid"


async def test_json_of_no_leads_is_an_empty_array() -> None:
    assert json.loads(await collect(write_json(rows()))) == []


@pytest.mark.parametrize("writer", [write_csv, write_json])
async def test_writers_stream_instead_of_materializing(writer) -> None:  # type: ignore[no-untyped-def]
    pulled = 0

    async def endless() -> AsyncIterator[LeadExport]:
        nonlocal pulled
        while True:
            pulled += 1
            yield make_row(pulled)

    chunks = writer(endless())
    produced = [await anext(chunks) for _ in range(3)]

    assert len(produced) == 3
    assert pulled <= 3
