from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import load_config
from app.db.models import Lead, LeadMerge, SourceRecord, SuppressionKind
from app.pipeline import run_collection
from app.repositories import LeadRepository, SuppressionRepository

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

CONFIG = load_config(Path("examples/configs/csv.yaml"))
TARGET = "info@nordicclean.test"


async def count(session: AsyncSession, model: type) -> int:
    return (await session.scalars(select(func.count()).select_from(model))).one()


async def find(session: AsyncSession, email: str) -> Lead | None:
    return (await session.scalars(select(Lead).where(Lead.email == email))).first()


async def test_deleting_a_lead_removes_its_records_and_merges(session: AsyncSession) -> None:
    await run_collection(session, CONFIG, "example_csv")
    lead = await find(session, TARGET)
    assert lead is not None

    records_before = await count(session, SourceRecord)
    merges_before = await count(session, LeadMerge)
    owned = len(
        (await session.scalars(select(SourceRecord).where(SourceRecord.lead_id == lead.id))).all()
    )
    assert owned == 3

    assert await LeadRepository(session).delete(lead.id) is True

    assert await find(session, TARGET) is None
    assert await count(session, SourceRecord) == records_before - owned
    assert await count(session, LeadMerge) < merges_before


async def test_deleting_a_missing_lead_reports_false(session: AsyncSession) -> None:
    assert await LeadRepository(session).delete(999999) is False


async def test_suppression_survives_the_next_collection(session: AsyncSession) -> None:
    await run_collection(session, CONFIG, "example_csv")
    lead = await find(session, TARGET)
    assert lead is not None

    suppressions = SuppressionRepository(session)
    await suppressions.add_for_lead(lead.email, lead.website_domain, reason="test erasure")
    await LeadRepository(session).delete(lead.id)
    assert await find(session, TARGET) is None

    stats = await run_collection(session, CONFIG, "example_csv")

    assert stats.suppressed == 3
    assert await find(session, TARGET) is None


async def test_suppression_only_blocks_what_it_names(session: AsyncSession) -> None:
    repo = SuppressionRepository(session)
    await repo.add(SuppressionKind.EMAIL, TARGET)

    stats = await run_collection(session, CONFIG, "example_csv")

    # two rows carry that address, one of them in upper case
    assert stats.suppressed == 2
    assert await find(session, TARGET) is None
    assert await find(session, "contact@helsinkifacility.test") is not None


async def test_email_suppression_alone_leaves_the_domain_reachable(
    session: AsyncSession,
) -> None:
    """Why deletion suppresses both: a row without an email still carries the company."""
    await SuppressionRepository(session).add(SuppressionKind.EMAIL, TARGET)
    await run_collection(session, CONFIG, "example_csv")

    assert await find(session, TARGET) is None
    surviving = (
        await session.scalars(select(Lead).where(Lead.website_domain == "nordicclean.test"))
    ).all()
    assert surviving != []


async def test_domain_suppression_blocks_every_address_on_it(session: AsyncSession) -> None:
    repo = SuppressionRepository(session)
    await repo.add(SuppressionKind.DOMAIN, "https://www.nordicclean.test/contact")

    stats = await run_collection(session, CONFIG, "example_csv")

    assert stats.suppressed == 3
    assert await find(session, TARGET) is None


async def test_suppression_values_are_normalized(session: AsyncSession) -> None:
    repo = SuppressionRepository(session)
    entry = await repo.add(SuppressionKind.EMAIL, "  INFO@NordicClean.TEST ")
    assert entry.value == TARGET

    domain = await repo.add(SuppressionKind.DOMAIN, "WWW.Example.COM/path")
    assert domain.value == "example.com"


async def test_adding_the_same_suppression_twice_is_idempotent(session: AsyncSession) -> None:
    repo = SuppressionRepository(session)
    first = await repo.add(SuppressionKind.EMAIL, TARGET)
    second = await repo.add(SuppressionKind.EMAIL, "INFO@NORDICCLEAN.TEST")

    assert first.id == second.id
    assert len(await repo.list_all()) == 1


async def test_removing_a_suppression_lets_collection_resume(session: AsyncSession) -> None:
    repo = SuppressionRepository(session)
    entry = await repo.add(SuppressionKind.EMAIL, TARGET)

    blocked = await run_collection(session, CONFIG, "example_csv")
    assert blocked.suppressed == 2

    assert await repo.remove(entry.id) is True
    resumed = await run_collection(session, CONFIG, "example_csv")

    assert resumed.suppressed == 0
    assert await find(session, TARGET) is not None


async def test_suppressed_records_are_not_stored_at_all(session: AsyncSession) -> None:
    await SuppressionRepository(session).add(SuppressionKind.DOMAIN, "nordicclean.test")
    await run_collection(session, CONFIG, "example_csv")

    stored = (
        await session.scalars(
            select(SourceRecord).where(SourceRecord.fp_domain == "nordicclean.test")
        )
    ).all()
    assert stored == []


async def test_retention_purges_only_stale_leads(session: AsyncSession) -> None:
    await run_collection(session, CONFIG, "example_csv")
    total = await count(session, Lead)

    stale_cutoff = datetime.now(UTC) - timedelta(days=400)
    stale = (await session.scalars(select(Lead).limit(4))).all()
    await session.execute(
        update(Lead)
        .where(Lead.id.in_([lead.id for lead in stale]))
        .values(last_seen_at=stale_cutoff)
    )

    repo = LeadRepository(session)
    assert await repo.count_older_than(365) == 4

    removed = await repo.purge_older_than(365)

    assert removed == 4
    assert await count(session, Lead) == total - 4


async def test_retention_keeps_everything_when_nothing_is_stale(session: AsyncSession) -> None:
    await run_collection(session, CONFIG, "example_csv")
    total = await count(session, Lead)

    assert await LeadRepository(session).purge_older_than(365) == 0
    assert await count(session, Lead) == total
