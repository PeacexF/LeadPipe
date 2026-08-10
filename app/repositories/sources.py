from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Source


class SourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def by_name(self, name: str) -> Source | None:
        stmt = select(Source).where(Source.name == name)
        return (await self.session.scalars(stmt)).first()

    async def list_all(self, enabled_only: bool = False) -> Sequence[Source]:
        stmt = select(Source).order_by(Source.name)
        if enabled_only:
            stmt = stmt.where(Source.enabled.is_(True))
        return (await self.session.scalars(stmt)).all()

    async def upsert(
        self,
        name: str,
        type: str,
        priority: int = 0,
        enabled: bool = True,
        config: dict[str, Any] | None = None,
    ) -> Source:
        source = await self.by_name(name)
        if source is None:
            source = Source(name=name)
            self.session.add(source)
        source.type = type
        source.priority = priority
        source.enabled = enabled
        source.config = config or {}
        await self.session.flush()
        return source
