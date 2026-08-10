import asyncio
import contextlib
import logging
import os
import socket
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.models import AppConfig
from app.jobs import queue
from app.jobs.queue import ClaimedJob
from app.pipeline import run_collection

logger = logging.getLogger(__name__)


def default_worker_name() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


@dataclass(slots=True)
class WorkerConfig:
    poll_interval: float = 1.0
    heartbeat_interval: float = 10.0
    stale_after: float = queue.STALE_AFTER_SECONDS
    recover_every: float = 30.0


class Worker:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        config: AppConfig,
        name: str | None = None,
        settings: WorkerConfig | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.config = config
        self.name = name or default_worker_name()
        self.settings = settings or WorkerConfig()
        self.stopping = asyncio.Event()
        self._last_recovery = 0.0

    def stop(self) -> None:
        self.stopping.set()

    async def run_forever(self) -> None:
        logger.info("worker=%s started", self.name)
        while not self.stopping.is_set():
            await self._maybe_recover()
            worked = await self.run_once()
            if not worked:
                await self._sleep(self.settings.poll_interval)
        logger.info("worker=%s stopped", self.name)

    async def run_once(self) -> bool:
        async with self.session_factory() as session:
            job = await queue.claim(session, self.name)
            await session.commit()
        if job is None:
            return False

        logger.info(
            "job=%s source=%s attempt=%s worker=%s claimed",
            job.id,
            job.source_name,
            job.attempts,
            self.name,
        )
        beat = asyncio.create_task(self._heartbeat(job.id))
        try:
            await self._process(job)
        except Exception as exc:
            await self._fail(job, exc)
        finally:
            beat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await beat
        return True

    async def _process(self, job: ClaimedJob) -> None:
        async with self.session_factory() as session:
            await run_collection(session, self.config, job.source_name, job_id=job.id)
            await session.commit()

    async def _fail(self, job: ClaimedJob, exc: Exception) -> None:
        async with self.session_factory() as session:
            status = await queue.fail(session, job, f"{type(exc).__name__}: {exc}")
            await session.commit()
        logger.error(
            "job=%s source=%s attempt=%s/%s failed -> %s: %s",
            job.id,
            job.source_name,
            job.attempts,
            job.max_attempts,
            status.value,
            exc,
        )

    async def _heartbeat(self, job_id: int) -> None:
        while True:
            await asyncio.sleep(self.settings.heartbeat_interval)
            async with self.session_factory() as session:
                await queue.heartbeat(session, job_id)
                await session.commit()

    async def _maybe_recover(self) -> None:
        now = asyncio.get_running_loop().time()
        if now - self._last_recovery < self.settings.recover_every:
            return
        self._last_recovery = now
        async with self.session_factory() as session:
            recovered = await queue.recover_stale(session, self.settings.stale_after)
            await session.commit()
        if recovered:
            logger.warning("worker=%s recovered %s stale job(s)", self.name, recovered)

    async def _sleep(self, seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self.stopping.wait(), timeout=seconds)
