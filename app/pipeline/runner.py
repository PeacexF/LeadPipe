import logging
from dataclasses import asdict, dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.models import AppConfig, SourceConfig
from app.db.models import JobStatus, Lead, Source
from app.deduplication import Candidate, MatchResult, fingerprints, match, merge
from app.domain.models import NormalizedLead, RawRecord
from app.normalization import normalize_record
from app.repositories import (
    JobRepository,
    LeadRepository,
    SourceRecordRepository,
    SourceRepository,
)
from app.sources import RecordError, SourceError, build_source
from app.validation import ValidationStatus, validate_lead

logger = logging.getLogger(__name__)

INITIAL_RULE = "initial"


@dataclass(slots=True)
class RunStats:
    collected: int = 0
    valid: int = 0
    invalid: int = 0
    unknown: int = 0
    duplicates: int = 0
    new_leads: int = 0
    needs_review: int = 0
    errors: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


async def run_collection(
    session: AsyncSession,
    config: AppConfig,
    source_name: str,
    job_id: int | None = None,
) -> RunStats:
    source_config = config.source(source_name)
    region = source_config.region or config.defaults.region

    sources = SourceRepository(session)
    source = await sources.upsert(
        name=source_config.name,
        type=source_config.type,
        priority=source_config.priority,
        enabled=source_config.enabled,
        config=source_config.options,
    )

    jobs = JobRepository(session)
    job = await jobs.get(job_id) if job_id is not None else await jobs.create(source.id)
    if job is None:
        raise SourceError(f"job {job_id} not found")
    await jobs.mark_running(job)

    stats = RunStats()
    try:
        adapter = build_source(source_config)
        for item in adapter.collect():
            if isinstance(item, RecordError):
                stats.errors += 1
                logger.warning("job=%s source=%s bad_record=%s", job.id, source.name, item.message)
                continue
            try:
                await _ingest(session, source, source_config, item, region, job.id, stats)
            except Exception:  # one bad record must not end the run
                stats.errors += 1
                logger.exception("job=%s source=%s record failed", job.id, source.name)
    except SourceError as exc:
        await jobs.save_results(job.id, **_persisted(stats))
        await jobs.mark_finished(job, JobStatus.FAILED, error=str(exc))
        logger.error("job=%s source=%s failed: %s", job.id, source.name, exc)
        raise

    await jobs.save_results(job.id, **_persisted(stats))
    await jobs.mark_finished(job, JobStatus.COMPLETED)
    logger.info("job=%s source=%s completed %s", job.id, source.name, stats.as_dict())
    return stats


async def _ingest(
    session: AsyncSession,
    source: Source,
    source_config: SourceConfig,
    raw: RawRecord,
    region: str | None,
    job_id: int,
    stats: RunStats,
) -> None:
    lead = normalize_record(raw, region)
    validation = validate_lead(lead)
    stats.collected += 1
    if validation.status is ValidationStatus.VALID:
        stats.valid += 1
    elif validation.status is ValidationStatus.INVALID:
        stats.invalid += 1
    else:
        stats.unknown += 1

    external_id = lead.extra.get("external_id")
    records = SourceRecordRepository(session)
    record, _ = await records.upsert(
        source_id=source.id,
        lead=lead,
        validation=validation,
        job_id=job_id,
        raw=dict(raw.raw),
        external_id=str(external_id) if external_id is not None else None,
    )

    leads = LeadRepository(session)
    own = await leads.get(record.lead_id) if record.lead_id is not None else None
    existing, result = await _best_match(leads, lead, exclude=own.id if own else None)

    if existing is not None and result is not None and result.auto_merge:
        await _remerge(leads, existing, lead, record.id, source_config.priority)
        await leads.link(existing.id, record.id, result.rule.value, result.confidence)
        stats.duplicates += 1
    elif own is not None:
        # already seen in an earlier run, so refresh its lead rather than making another
        await _remerge(leads, own, lead, record.id, source_config.priority)
        stats.duplicates += 1
    else:
        merged = merge([Candidate(lead, str(record.id), source_config.priority)])
        created = await leads.create(merged, validation)
        await leads.link(created.id, record.id, INITIAL_RULE, 1.0)
        stats.new_leads += 1

    if existing is not None and result is not None and not result.auto_merge:
        # kept separate, but recorded as a candidate duplicate for review
        await leads.link(
            existing.id,
            record.id,
            result.rule.value,
            result.confidence,
            needs_review=True,
            claim=False,
        )
        stats.needs_review += 1


async def _remerge(
    leads: LeadRepository,
    lead_row: Lead,
    incoming: NormalizedLead,
    record_id: int,
    priority: int,
) -> None:
    candidates = [c for c in await leads.candidates_for(lead_row.id) if c.origin != str(record_id)]
    candidates.append(Candidate(incoming, str(record_id), priority))
    merged = merge(candidates)
    await leads.update(lead_row, merged, validate_lead(merged.lead))


async def _best_match(
    leads: LeadRepository, lead: NormalizedLead, exclude: int | None = None
) -> tuple[Lead | None, MatchResult | None]:
    best: tuple[Lead | None, MatchResult | None] = (None, None)
    for candidate in await leads.find_candidates(fingerprints(lead)):
        if candidate.id == exclude:
            continue
        result = match(lead, _as_normalized(candidate, lead))
        if result is None:
            continue
        current = best[1]
        if current is None or result.confidence > current.confidence:
            best = (candidate, result)
    return best


def _as_normalized(stored: Lead, incoming: NormalizedLead) -> NormalizedLead:
    return NormalizedLead(
        source=incoming.source,
        collected_at=stored.last_seen_at,
        company_name=stored.company_name,
        contact_name=stored.contact_name,
        website=stored.website,
        website_domain=stored.website_domain,
        email=stored.email,
        phone=stored.phone,
        address=stored.address,
        city=stored.city,
        country=stored.country,
        extra={},
    )


def _persisted(stats: RunStats) -> dict[str, int]:
    return {
        "collected": stats.collected,
        "valid": stats.valid,
        "invalid": stats.invalid,
        "duplicates": stats.duplicates,
        "new_leads": stats.new_leads,
        "errors": stats.errors,
    }
