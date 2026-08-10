import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import load_config
from app.db.models import CollectionJob, JobStatus, Lead, LeadMerge, Source, SourceRecord
from app.db.session import create_session_factory
from app.jobs import Worker, WorkerConfig, queue
from app.jobs.service import enqueue, sync_sources

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

CONFIG = load_config(Path("examples/configs/csv.yaml"))


@pytest_asyncio.fixture(loop_scope="session")
async def factory(engine: AsyncEngine) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Real committed sessions: SKIP LOCKED needs separate connections, not savepoints."""
    maker = create_session_factory(engine)
    async with maker() as session:
        await sync_sources(session, CONFIG)
        await session.commit()
    try:
        yield maker
    finally:
        async with maker() as session:
            for model in (LeadMerge, SourceRecord, Lead, CollectionJob, Source):
                await session.execute(delete(model))
            await session.commit()


async def queue_jobs(factory: async_sessionmaker[AsyncSession], count: int) -> list[int]:
    async with factory() as session:
        jobs = [await enqueue(session, CONFIG, "example_csv") for _ in range(count)]
        await session.commit()
        return [job.id for job in jobs]


async def test_two_workers_never_claim_the_same_job(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    expected = await queue_jobs(factory, 8)

    async def drain(name: str) -> list[int]:
        claimed = []
        while True:
            async with factory() as session:
                job = await queue.claim(session, name)
                await session.commit()
            if job is None:
                return claimed
            claimed.append(job.id)
            await asyncio.sleep(0)

    left, right = await asyncio.gather(drain("worker-a"), drain("worker-b"))

    assert set(left) & set(right) == set()
    assert sorted(left + right) == sorted(expected)
    assert len(left + right) == len(expected)


async def test_claim_returns_none_on_an_empty_queue(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as session:
        assert await queue.claim(session, "worker") is None


async def test_claim_respects_run_after(factory: async_sessionmaker[AsyncSession]) -> None:
    [job_id] = await queue_jobs(factory, 1)
    async with factory() as session:
        await session.execute(
            update(CollectionJob)
            .where(CollectionJob.id == job_id)
            .values(run_after=datetime.now(UTC) + timedelta(hours=1))
        )
        await session.commit()

    async with factory() as session:
        assert await queue.claim(session, "worker") is None


async def test_failure_requeues_until_attempts_run_out(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    [job_id] = await queue_jobs(factory, 1)

    async with factory() as session:
        job = await queue.claim(session, "worker")
        assert job is not None
        assert await queue.fail(session, job, "boom") is JobStatus.PENDING
        await session.commit()

    async with factory() as session:
        stored = await session.get(CollectionJob, job_id)
        assert stored is not None
        assert stored.status is JobStatus.PENDING
        assert stored.attempts == 1
        assert stored.run_after is not None
        assert stored.error == "boom"

        # clear the backoff so the next attempt is claimable straight away
        await session.execute(
            update(CollectionJob).where(CollectionJob.id == job_id).values(run_after=None)
        )
        await session.commit()

    for _ in range(2):
        async with factory() as session:
            job = await queue.claim(session, "worker")
            assert job is not None
            status = await queue.fail(session, job, "boom")
            await session.execute(
                update(CollectionJob).where(CollectionJob.id == job_id).values(run_after=None)
            )
            await session.commit()

    assert status is JobStatus.FAILED
    async with factory() as session:
        stored = await session.get(CollectionJob, job_id)
        assert stored is not None
        assert stored.status is JobStatus.FAILED
        assert stored.attempts == 3
        assert stored.finished_at is not None


async def test_stale_running_job_is_recovered(factory: async_sessionmaker[AsyncSession]) -> None:
    [job_id] = await queue_jobs(factory, 1)
    async with factory() as session:
        job = await queue.claim(session, "worker-that-died")
        assert job is not None
        await session.execute(
            update(CollectionJob)
            .where(CollectionJob.id == job_id)
            .values(heartbeat_at=datetime.now(UTC) - timedelta(minutes=10))
        )
        await session.commit()

    async with factory() as session:
        assert await queue.recover_stale(session, stale_after=60) == 1
        await session.commit()

    async with factory() as session:
        stored = await session.get(CollectionJob, job_id)
        assert stored is not None
        assert stored.status is JobStatus.PENDING
        assert stored.claimed_by is None

        reclaimed = await queue.claim(session, "worker-b")
        assert reclaimed is not None
        assert reclaimed.attempts == 2


async def test_stale_job_out_of_attempts_fails(factory: async_sessionmaker[AsyncSession]) -> None:
    [job_id] = await queue_jobs(factory, 1)
    async with factory() as session:
        await queue.claim(session, "worker")
        await session.execute(
            update(CollectionJob)
            .where(CollectionJob.id == job_id)
            .values(attempts=3, heartbeat_at=datetime.now(UTC) - timedelta(minutes=10))
        )
        await session.commit()

    async with factory() as session:
        await queue.recover_stale(session, stale_after=60)
        await session.commit()

    async with factory() as session:
        stored = await session.get(CollectionJob, job_id)
        assert stored is not None
        assert stored.status is JobStatus.FAILED
        assert stored.error == "worker stopped responding"


async def test_heartbeat_keeps_a_job_out_of_recovery(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    [job_id] = await queue_jobs(factory, 1)
    async with factory() as session:
        await queue.claim(session, "worker")
        await session.commit()

    async with factory() as session:
        await queue.heartbeat(session, job_id)
        await session.commit()

    async with factory() as session:
        assert await queue.recover_stale(session, stale_after=60) == 0


async def test_worker_runs_a_queued_job_end_to_end(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    [job_id] = await queue_jobs(factory, 1)
    worker = Worker(factory, CONFIG, name="test-worker", settings=WorkerConfig(poll_interval=0.01))

    assert await worker.run_once() is True

    async with factory() as session:
        job = await session.get(CollectionJob, job_id)
        assert job is not None
        assert job.status is JobStatus.COMPLETED
        assert job.claimed_by == "test-worker"

        leads = (await session.scalars(select(Lead))).all()
        assert len(leads) == 15
        records = (await session.scalars(select(SourceRecord))).all()
        assert all(record.job_id == job_id for record in records)


async def test_worker_reports_no_work_on_an_empty_queue(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    worker = Worker(factory, CONFIG, name="idle", settings=WorkerConfig(poll_interval=0.01))
    assert await worker.run_once() is False


async def test_worker_retries_a_failing_source(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    config_file = tmp_path / "broken.yaml"
    config_file.write_text(
        "sources:\n"
        "  - name: example_csv\n"
        "    type: csv\n"
        "    path: ./does-not-exist.csv\n"
        "    mapping:\n"
        "      company_name: name\n"
    )
    broken = load_config(config_file)

    [job_id] = await queue_jobs(factory, 1)
    worker = Worker(factory, broken, name="test-worker", settings=WorkerConfig(poll_interval=0.01))

    assert await worker.run_once() is True

    async with factory() as session:
        job = await session.get(CollectionJob, job_id)
        assert job is not None
        assert job.status is JobStatus.PENDING
        assert job.attempts == 1
        assert job.error is not None
        assert "file not found" in job.error
        assert (await session.scalars(select(Lead))).all() == []


async def test_worker_stops_when_asked(factory: async_sessionmaker[AsyncSession]) -> None:
    worker = Worker(factory, CONFIG, name="stoppable", settings=WorkerConfig(poll_interval=5.0))
    task = asyncio.create_task(worker.run_forever())
    await asyncio.sleep(0.05)

    worker.stop()
    await asyncio.wait_for(task, timeout=2.0)

    assert task.done()
