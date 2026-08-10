import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import load_config
from app.db.models import (
    CollectionJob,
    CollectionJobResult,
    Lead,
    LeadMerge,
    Source,
    SourceRecord,
)
from app.db.session import create_engine, create_session_factory
from app.jobs.service import sync_sources

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_CONFIG = load_config(ROOT / "examples/configs/csv.yaml")

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    configured = os.getenv("TEST_DATABASE_URL")
    if configured:
        yield configured
        return

    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as container:
        yield container.get_connection_url()


@pytest.fixture(scope="session", autouse=True)
def migrated(database_url: str) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(database_url)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def factory(engine: AsyncEngine) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Committed sessions: concurrency and streaming need real connections, not savepoints."""
    maker = create_session_factory(engine)
    async with maker() as db:
        await sync_sources(db, EXAMPLE_CONFIG)
        await db.commit()
    try:
        yield maker
    finally:
        async with maker() as db:
            for model in (
                LeadMerge,
                SourceRecord,
                Lead,
                CollectionJobResult,
                CollectionJob,
                Source,
            ):
                await db.execute(delete(model))
            await db.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with engine.connect() as connection:
        transaction = await connection.begin()
        db = AsyncSession(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield db
        finally:
            await db.close()
            await transaction.rollback()
