import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db.session import create_engine

ROOT = Path(__file__).resolve().parents[2]

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
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with engine.connect() as connection:
        transaction = await connection.begin()
        db = AsyncSession(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield db
        finally:
            await db.close()
            await transaction.rollback()
