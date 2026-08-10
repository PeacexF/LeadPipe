from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import JobStatus
from app.deduplication import Candidate, MatchRule, fingerprints, merge
from app.domain import RawRecord, SourceRef
from app.normalization import normalize_record
from app.repositories import (
    JobRepository,
    LeadRepository,
    SourceRecordRepository,
    SourceRepository,
)
from app.validation import validate_lead

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

EARLY = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
LATE = EARLY + timedelta(days=7)


def lead_from(source: str, collected_at: datetime = EARLY, **fields: str | None):  # type: ignore[no-untyped-def]
    return normalize_record(
        RawRecord(
            source=SourceRef(name=source, url=f"https://{source}.test/1"),
            fields=fields,
            collected_at=collected_at,
        )
    )


async def store(session: AsyncSession, source_name: str, priority: int = 0, **fields: str | None):  # type: ignore[no-untyped-def]
    source = await SourceRepository(session).upsert(source_name, type="csv", priority=priority)
    lead = lead_from(source_name, **fields)  # type: ignore[arg-type]
    record, is_new = await SourceRecordRepository(session).upsert(
        source_id=source.id, lead=lead, validation=validate_lead(lead), raw=dict(fields)
    )
    return source, lead, record, is_new


async def test_source_upsert_is_idempotent(session: AsyncSession) -> None:
    repo = SourceRepository(session)
    first = await repo.upsert("example_csv", type="csv", priority=1)
    second = await repo.upsert("example_csv", type="csv", priority=5)

    assert first.id == second.id
    assert second.priority == 5
    assert len(await repo.list_all()) == 1


async def test_record_is_inserted_then_updated_on_second_sighting(session: AsyncSession) -> None:
    _, _, record, is_new = await store(
        session, "example_csv", company_name="Example Services", email="contact@example.com"
    )
    assert is_new
    assert record.fp_email == "contact@example.com"

    _, _, again, is_new_again = await store(
        session, "example_csv", company_name="Example Services", email="contact@example.com"
    )
    assert not is_new_again
    assert again.id == record.id


async def test_records_with_external_id_key_on_it(session: AsyncSession) -> None:
    source = await SourceRepository(session).upsert("example_api", type="api")
    repo = SourceRecordRepository(session)

    first = lead_from("example_api", company_name="Example", email="a@example.com")
    record, is_new = await repo.upsert(source.id, first, validate_lead(first), external_id="ACME-1")
    assert is_new

    renamed = lead_from("example_api", company_name="Example Renamed", email="a@example.com")
    same, is_new_again = await repo.upsert(
        source.id, renamed, validate_lead(renamed), external_id="ACME-1"
    )
    assert not is_new_again
    assert same.id == record.id
    assert same.normalized["company_name"] == "Example Renamed"


async def test_lead_is_created_and_found_by_fingerprint(session: AsyncSession) -> None:
    _, lead, record, _ = await store(
        session, "example_csv", company_name="Example Services", email="contact@example.com"
    )
    repo = LeadRepository(session)
    merged = merge([Candidate(lead=lead, origin=str(record.id))])
    stored = await repo.create(merged, validate_lead(lead))
    await repo.link(stored.id, record.id, MatchRule.EMAIL.value, 1.0)

    candidates = await repo.find_candidates(fingerprints(lead))
    assert [c.id for c in candidates] == [stored.id]


async def test_name_and_location_candidates_use_trigram_similarity(session: AsyncSession) -> None:
    _, lead, record, _ = await store(
        session, "example_csv", company_name="Example Services Oy", city="Helsinki", country="FI"
    )
    repo = LeadRepository(session)
    stored = await repo.create(
        merge([Candidate(lead=lead, origin=str(record.id))]), validate_lead(lead)
    )

    near = lead_from(
        "example_api", company_name="Example Service", city="HELSINKI", country="Finland"
    )
    assert [c.id for c in await repo.find_candidates(fingerprints(near))] == [stored.id]

    unrelated = lead_from(
        "example_api", company_name="Nordic Logistics", city="Helsinki", country="FI"
    )
    assert await repo.find_candidates(fingerprints(unrelated)) == []


async def test_two_sources_merge_into_one_lead_with_provenance(session: AsyncSession) -> None:
    _, csv_lead, csv_record, _ = await store(
        session,
        "example_csv",
        company_name="Example Services",
        email="contact@example.com",
        city="Helsinki",
        country="Finland",
    )
    _, api_lead, api_record, _ = await store(
        session,
        "example_api",
        priority=10,
        company_name="EXAMPLE SERVICES LTD",
        email="CONTACT@EXAMPLE.COM",
        phone="+358401234567",
    )

    repo = LeadRepository(session)
    first = await repo.create(
        merge([Candidate(csv_lead, str(csv_record.id))]), validate_lead(csv_lead)
    )
    await repo.link(first.id, csv_record.id, MatchRule.EMAIL.value, 1.0)

    candidates = await repo.find_candidates(fingerprints(api_lead))
    assert [c.id for c in candidates] == [first.id]

    merged = merge(
        [
            Candidate(csv_lead, str(csv_record.id)),
            Candidate(api_lead, str(api_record.id), priority=10),
        ]
    )
    await repo.update(first, merged, validate_lead(merged.lead))
    await repo.link(first.id, api_record.id, MatchRule.EMAIL.value, 1.0)

    assert first.phone == "+358401234567"
    assert first.city == "Helsinki"

    provenance = await repo.provenance(first.id)
    assert {p.source_name for p in provenance} == {"example_csv", "example_api"}
    assert {p.rule for p in provenance} == {"email"}


async def test_last_seen_at_advances_without_moving_first_seen_at(session: AsyncSession) -> None:
    _, lead, record, _ = await store(session, "example_csv", company_name="Example")
    repo = LeadRepository(session)
    stored = await repo.create(merge([Candidate(lead, str(record.id))]), validate_lead(lead))
    assert stored.first_seen_at == EARLY
    assert stored.last_seen_at == EARLY

    later = lead_from("example_csv", collected_at=LATE, company_name="Example")
    await repo.update(stored, merge([Candidate(later, str(record.id))]), validate_lead(later))

    assert stored.first_seen_at == EARLY
    assert stored.last_seen_at == LATE


async def test_linking_is_idempotent(session: AsyncSession) -> None:
    _, lead, record, _ = await store(session, "example_csv", company_name="Example")
    repo = LeadRepository(session)
    stored = await repo.create(merge([Candidate(lead, str(record.id))]), validate_lead(lead))

    await repo.link(stored.id, record.id, MatchRule.EMAIL.value, 1.0)
    await repo.link(stored.id, record.id, MatchRule.NAME_LOCATION.value, 0.8, needs_review=True)

    provenance = await repo.provenance(stored.id)
    assert len(provenance) == 1
    assert provenance[0].rule == "name_location"
    assert provenance[0].needs_review


async def test_job_lifecycle_and_results(session: AsyncSession) -> None:
    source = await SourceRepository(session).upsert("example_csv", type="csv")
    repo = JobRepository(session)

    job = await repo.create(source.id)
    assert job.status is JobStatus.PENDING

    await repo.mark_running(job)
    assert job.status is JobStatus.RUNNING
    assert job.started_at is not None

    await repo.save_results(
        job.id, collected=1284, valid=1107, invalid=177, duplicates=193, new_leads=914
    )
    await repo.mark_finished(job, JobStatus.COMPLETED)

    stored = await repo.get(job.id)
    assert stored is not None
    assert stored.status is JobStatus.COMPLETED
    assert stored.finished_at is not None
