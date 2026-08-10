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
def html_config(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Serve the shipped fixture site from disk, robots.txt included."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = DATA / request.url.path.lstrip("/")
        if not path.is_file():
            return httpx.Response(404, text="not found")
        return httpx.Response(200, text=path.read_text())

    transport = httpx.MockTransport(handler)
    original = _REGISTRY["html"]

    def factory(config: Any) -> Any:
        fetcher = Fetcher(
            policy=FetchPolicy(requests_per_second=0, retries=0, allow_private_hosts=True),
            client=httpx.AsyncClient(transport=transport),
            resolver=lambda host: ["93.184.216.34"],
        )
        return original(config, fetcher)  # type: ignore[call-arg]

    monkeypatch.setitem(_REGISTRY, "html", factory)
    return load_config(Path("examples/configs/html.yaml"))


async def count(session: AsyncSession, model: type) -> int:
    return (await session.scalars(select(func.count()).select_from(model))).one()


async def test_collects_both_pages_of_the_directory(
    session: AsyncSession, html_config: Any
) -> None:
    stats = await run_collection(session, html_config, "example_directory")

    # 5 listings on page one, 3 on page two, one of which is blocked by robots.txt
    assert stats.collected == 7
    assert stats.errors == 1
    assert await count(session, SourceRecord) == 7


async def test_robots_blocked_detail_page_is_never_collected(
    session: AsyncSession, html_config: Any
) -> None:
    await run_collection(session, html_config, "example_directory")

    records = (await session.scalars(select(SourceRecord))).all()
    assert all("hidden" not in (record.source_url or "") for record in records)
    assert not (
        await session.scalars(select(Lead).where(Lead.company_name == "Hidden Holdings Oy"))
    ).all()


async def test_detail_pages_enrich_listing_rows(session: AsyncSession, html_config: Any) -> None:
    await run_collection(session, html_config, "example_directory")

    lead = (
        await session.scalars(select(Lead).where(Lead.website_domain == "nordicclean.test"))
    ).one()

    assert lead.company_name == "Nordic Clean Oy"
    assert lead.contact_name == "Anna Virtanen"
    assert lead.address == "Mannerheimintie 12"
    assert lead.city == "Helsinki"
    assert lead.country == "FI"
    assert lead.email == "info@nordicclean.test"
    assert lead.phone == "+358401234567"


async def test_rows_without_a_detail_page_still_land(
    session: AsyncSession, html_config: Any
) -> None:
    await run_collection(session, html_config, "example_directory")

    lead = (
        await session.scalars(select(Lead).where(Lead.company_name == "Savonlinna Siivous Ky"))
    ).one()
    assert lead.email == "myynti@savonlinnasiivous.test"
    assert lead.contact_name is None


async def test_html_leads_merge_with_the_csv_source(
    session: AsyncSession, html_config: Any
) -> None:
    await run_collection(session, CSV_CONFIG, "example_csv")
    html_stats = await run_collection(session, html_config, "example_directory")

    assert html_stats.duplicates > 0

    lead = (
        await session.scalars(select(Lead).where(Lead.website_domain == "nordicclean.test"))
    ).one()
    provenance = await LeadRepository(session).provenance(lead.id)
    sources = {item.source_name for item in provenance if not item.needs_review}
    assert sources == {"example_csv", "example_directory"}


async def test_rerunning_is_idempotent(session: AsyncSession, html_config: Any) -> None:
    await run_collection(session, html_config, "example_directory")
    leads = await count(session, Lead)
    records = await count(session, SourceRecord)

    await run_collection(session, html_config, "example_directory")

    assert await count(session, Lead) == leads
    assert await count(session, SourceRecord) == records
