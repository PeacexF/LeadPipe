from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import load_config
from app.db.models import CollectionJobResult, JobStatus, Lead, LeadMerge, SourceRecord
from app.pipeline import run_collection
from app.repositories import LeadRepository

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

CONFIG = Path("examples/configs/csv.yaml")


async def count(session: AsyncSession, model: type) -> int:
    return (await session.scalars(select(func.count()).select_from(model))).one()


async def test_end_to_end_collection_of_the_example_dataset(session: AsyncSession) -> None:
    stats = await run_collection(session, load_config(CONFIG), "example_csv")

    assert stats.collected == 20
    assert stats.errors == 0
    assert stats.duplicates > 0
    assert stats.new_leads < stats.collected
    assert stats.new_leads + stats.duplicates == stats.collected
    assert stats.valid + stats.invalid + stats.unknown == stats.collected

    assert await count(session, SourceRecord) == 20
    assert await count(session, Lead) == stats.new_leads


async def test_duplicates_across_rows_resolve_to_one_lead(session: AsyncSession) -> None:
    await run_collection(session, load_config(CONFIG), "example_csv")

    stmt = select(Lead).where(Lead.email == "info@nordicclean.test")
    lead = (await session.scalars(stmt)).one()

    provenance = await LeadRepository(session).provenance(lead.id)
    merged = [p for p in provenance if not p.needs_review]
    assert len(merged) == 3
    assert lead.company_name == "Nordic Clean Oy"
    assert lead.phone == "+358401234567"
    assert lead.city == "Helsinki"
    assert lead.country == "FI"


async def test_similar_name_in_same_city_is_flagged_not_merged(session: AsyncSession) -> None:
    await run_collection(session, load_config(CONFIG), "example_csv")

    review = (
        await session.scalars(select(LeadMerge).where(LeadMerge.needs_review.is_(True)))
    ).all()
    assert review != []
    assert all(item.rule == "name_location" for item in review)

    flagged = await session.get(SourceRecord, review[0].source_record_id)
    assert flagged is not None
    assert flagged.lead_id != review[0].lead_id


async def test_same_name_different_city_stays_separate(session: AsyncSession) -> None:
    await run_collection(session, load_config(CONFIG), "example_csv")

    turku = (
        await session.scalars(select(Lead).where(Lead.email == "turku@nordicclean-turku.test"))
    ).one()
    helsinki = (
        await session.scalars(select(Lead).where(Lead.email == "info@nordicclean.test"))
    ).one()
    assert turku.id != helsinki.id


async def test_invalid_records_are_kept_and_flagged(session: AsyncSession) -> None:
    stats = await run_collection(session, load_config(CONFIG), "example_csv")
    assert stats.invalid > 0

    stmt = select(SourceRecord).where(SourceRecord.validation_status == "invalid")
    invalid = (await session.scalars(stmt)).all()
    assert invalid != []
    assert all(record.lead_id is not None for record in invalid)


async def test_rerunning_a_source_does_not_duplicate(session: AsyncSession) -> None:
    config = load_config(CONFIG)
    first = await run_collection(session, config, "example_csv")
    leads_after_first = await count(session, Lead)

    second = await run_collection(session, config, "example_csv")

    assert second.collected == first.collected
    assert await count(session, SourceRecord) == 20
    assert await count(session, Lead) == leads_after_first


async def test_job_is_recorded_with_results(session: AsyncSession) -> None:
    stats = await run_collection(session, load_config(CONFIG), "example_csv")

    result = (await session.scalars(select(CollectionJobResult))).one()
    assert result.collected == stats.collected
    assert result.new_leads == stats.new_leads
    assert result.duplicates == stats.duplicates

    job = await session.get(type(result).job.property.mapper.class_, result.job_id)
    assert job is not None
    assert job.status is JobStatus.COMPLETED
    assert job.started_at is not None
    assert job.finished_at is not None
