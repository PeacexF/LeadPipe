import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import CursorResult, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CollectionJob, JobStatus, Source

BASE_BACKOFF_SECONDS = 5.0
MAX_BACKOFF_SECONDS = 300.0
STALE_AFTER_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    id: int
    source_id: int
    source_name: str
    attempts: int
    max_attempts: int


def backoff_seconds(attempts: int, jitter: float | None = None) -> float:
    # Exponential, capped, with jitter so retries do not synchronise
    delay = min(BASE_BACKOFF_SECONDS * 2 ** max(attempts - 1, 0), MAX_BACKOFF_SECONDS)
    spread = jitter if jitter is not None else random.random()
    return float(delay * (0.5 + 0.5 * spread))


async def claim(session: AsyncSession, worker: str) -> ClaimedJob | None:
    # Take the oldest runnable job. SKIP LOCKED keeps concurrent workers off each other
    now = datetime.now(UTC)
    candidate = (
        select(CollectionJob.id)
        .where(
            CollectionJob.status == JobStatus.PENDING,
            or_(CollectionJob.run_after.is_(None), CollectionJob.run_after <= now),
        )
        .order_by(CollectionJob.created_at, CollectionJob.id)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    stmt = (
        update(CollectionJob)
        .where(CollectionJob.id == candidate)
        .values(
            status=JobStatus.RUNNING,
            started_at=func.coalesce(CollectionJob.started_at, now),
            heartbeat_at=now,
            attempts=CollectionJob.attempts + 1,
            claimed_by=worker,
            run_after=None,
        )
        .returning(
            CollectionJob.id,
            CollectionJob.source_id,
            CollectionJob.attempts,
            CollectionJob.max_attempts,
        )
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return None

    job_id, source_id, attempts, max_attempts = row
    name = await session.scalar(select(Source.name).where(Source.id == source_id))
    return ClaimedJob(
        id=job_id,
        source_id=source_id,
        source_name=str(name),
        attempts=attempts,
        max_attempts=max_attempts,
    )


async def heartbeat(session: AsyncSession, job_id: int) -> None:
    await session.execute(
        update(CollectionJob)
        .where(CollectionJob.id == job_id, CollectionJob.status == JobStatus.RUNNING)
        .values(heartbeat_at=datetime.now(UTC))
    )


async def fail(session: AsyncSession, job: ClaimedJob, error: str) -> JobStatus:
    # Back to pending while retries remain, otherwise terminally failed
    now = datetime.now(UTC)
    if job.attempts < job.max_attempts:
        await session.execute(
            update(CollectionJob)
            .where(CollectionJob.id == job.id)
            .values(
                status=JobStatus.PENDING,
                error=error[:2000],
                claimed_by=None,
                finished_at=None,
                run_after=now + timedelta(seconds=backoff_seconds(job.attempts)),
            )
        )
        return JobStatus.PENDING

    await session.execute(
        update(CollectionJob)
        .where(CollectionJob.id == job.id)
        .values(status=JobStatus.FAILED, error=error[:2000], claimed_by=None, finished_at=now)
    )
    return JobStatus.FAILED


async def recover_stale(session: AsyncSession, stale_after: float = STALE_AFTER_SECONDS) -> int:
    # Requeue jobs whose worker stopped heartbeating
    cutoff = datetime.now(UTC) - timedelta(seconds=stale_after)
    running = CollectionJob.status == JobStatus.RUNNING
    silent = or_(CollectionJob.heartbeat_at.is_(None), CollectionJob.heartbeat_at < cutoff)

    exhausted = await session.execute(
        update(CollectionJob)
        .where(running, silent, CollectionJob.attempts >= CollectionJob.max_attempts)
        .values(
            status=JobStatus.FAILED,
            error="worker stopped responding",
            claimed_by=None,
            finished_at=datetime.now(UTC),
        )
    )
    requeued = await session.execute(
        update(CollectionJob)
        .where(running, silent)
        .values(status=JobStatus.PENDING, claimed_by=None, run_after=None)
    )
    return _rowcount(exhausted) + _rowcount(requeued)


def _rowcount(result: object) -> int:
    return result.rowcount if isinstance(result, CursorResult) else 0
