from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.settings import get_settings


def create_engine(url: str | None = None, echo: bool = False) -> AsyncEngine:
    return create_async_engine(url or get_settings().database_url, echo=echo, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
