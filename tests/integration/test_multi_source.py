import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import load_config
from app.db.models import Lead, SourceRecord
from app.fetch import Fetcher, FetchPolicy
from app.pipeline import run_collection
from app.repositories import LeadRepository
from app.sources.registry import _REGISTRY

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

CSV_CONFIG = load_config(Path("examples/configs/csv.yaml"))
DATA = Path("examples/data")


@pytest.fixture
def api_config(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Serve the shipped fixture files from memory, so no server is needed."""

    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.lstrip("/")
        if name == "robots.txt":
            return httpx.Response(200, text=(DATA / "robots.txt").read_text())
        path = DATA / name
        if not path.is_file():
            return httpx.Response(404)
        return httpx.Response(200, text=path.read_text())

    transport = httpx.MockTransport(handler)
    original = _REGISTRY["api"]

    def factory(config: Any) -> Any:
        fetcher = Fetcher(
            policy=FetchPolicy(requests_per_second=0, retries=0, allow_private_hosts=True),
            client=httpx.AsyncClient(transport=transport),
            resolver=lambda host: ["93.184.216.34"],
        )
        return original(config, fetcher)  # type: ignore[call-arg]

    monkeypatch.setitem(_REGISTRY, "api", factory)
    return load_config(Path("examples/configs/api.yaml"))


async def count(session: AsyncSession, model: type) -> int:
    return (await session.scalars(select(func.count()).select_from(model))).one()


async def test_api_source_collects_both_pages(session: AsyncSession, api_config: Any) -> None:
    stats = await run_collection(session, api_config, "example_api")

    page_one = json.loads((DATA / "companies_api.json").read_text())["data"]
    page_two = json.loads((DATA / "companies_api_page2.json").read_text())["data"]
    objects = [item for item in page_one + page_two if isinstance(item, dict)]

    assert stats.collected == len(objects)
    assert stats.errors == 1  # the deliberate non-object row on page one
    assert await count(session, SourceRecord) == len(objects)


async def test_nested_fields_are_mapped_and_normalized(
    session: AsyncSession, api_config: Any
) -> None:
    await run_collection(session, api_config, "example_api")

    lead = (
        await session.scalars(select(Lead).where(Lead.email == "post@bergenrenhold.test"))
    ).one()
    assert lead.company_name == "Bergen Renhold AS"
    assert lead.contact_name == "Ola Nordmann"
    assert lead.phone == "+4755123456"
    assert lead.city == "Bergen"
    assert lead.country == "NO"


async def test_leads_merge_across_sources(session: AsyncSession, api_config: Any) -> None:
    csv_stats = await run_collection(session, CSV_CONFIG, "example_csv")
    api_stats = await run_collection(session, api_config, "example_api")

    total_records = csv_stats.collected + api_stats.collected
    assert await count(session, SourceRecord) == total_records
    assert api_stats.duplicates > 0
    assert await count(session, Lead) < total_records

    merged = (
        await session.scalars(select(Lead).where(Lead.website_domain == "nordicclean.test"))
    ).one()
    provenance = await LeadRepository(session).provenance(merged.id)
    sources = {item.source_name for item in provenance if not item.needs_review}
    assert sources == {"example_csv", "example_api"}


async def test_higher_priority_source_wins_conflicting_fields(
    session: AsyncSession, api_config: Any
) -> None:
    await run_collection(session, CSV_CONFIG, "example_csv")
    await run_collection(session, api_config, "example_api")

    lead = (
        await session.scalars(select(Lead).where(Lead.website_domain == "nordicclean.test"))
    ).one()

    # the api source has priority 10, the csv source 0
    assert lead.email == "anna.virtanen@nordicclean.test"
    assert lead.address == "Mannerheimintie 12 A"


async def test_collection_order_does_not_change_the_result(
    session: AsyncSession, api_config: Any
) -> None:
    await run_collection(session, api_config, "example_api")
    await run_collection(session, CSV_CONFIG, "example_csv")

    lead = (
        await session.scalars(select(Lead).where(Lead.website_domain == "nordicclean.test"))
    ).one()
    assert lead.email == "anna.virtanen@nordicclean.test"
    assert lead.address == "Mannerheimintie 12 A"


async def test_rerunning_both_sources_is_idempotent(session: AsyncSession, api_config: Any) -> None:
    await run_collection(session, CSV_CONFIG, "example_csv")
    await run_collection(session, api_config, "example_api")
    leads_after_first = await count(session, Lead)
    records_after_first = await count(session, SourceRecord)

    await run_collection(session, CSV_CONFIG, "example_csv")
    await run_collection(session, api_config, "example_api")

    assert await count(session, Lead) == leads_after_first
    assert await count(session, SourceRecord) == records_after_first
