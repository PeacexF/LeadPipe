from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Suppression, SuppressionKind
from app.domain.models import NormalizedLead
from app.normalization import extract_domain, normalize_email, normalize_url
from app.repositories._rows import rowcount


@dataclass(frozen=True, slots=True)
class SuppressionList:
    """The set a collection checks each record against."""

    emails: frozenset[str] = field(default_factory=frozenset)
    domains: frozenset[str] = field(default_factory=frozenset)

    def blocks(self, lead: NormalizedLead) -> str | None:
        if lead.email and lead.email in self.emails:
            return "email"
        if lead.website_domain and lead.website_domain in self.domains:
            return "domain"
        return None

    def __bool__(self) -> bool:
        return bool(self.emails or self.domains)


def normalize_value(kind: SuppressionKind, value: str) -> str:
    if kind is SuppressionKind.EMAIL:
        return normalize_email(value) or value.strip().lower()
    return extract_domain(normalize_url(value)) or value.strip().lower()


class SuppressionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_all(self) -> Sequence[Suppression]:
        stmt = select(Suppression).order_by(Suppression.kind, Suppression.value)
        return (await self.session.scalars(stmt)).all()

    async def load(self) -> SuppressionList:
        entries = await self.list_all()
        return SuppressionList(
            emails=frozenset(
                entry.value for entry in entries if entry.kind is SuppressionKind.EMAIL
            ),
            domains=frozenset(
                entry.value for entry in entries if entry.kind is SuppressionKind.DOMAIN
            ),
        )

    async def add(
        self, kind: SuppressionKind, value: str, reason: str | None = None
    ) -> Suppression:
        normalized = normalize_value(kind, value)
        stmt = select(Suppression).where(Suppression.kind == kind, Suppression.value == normalized)
        existing = (await self.session.scalars(stmt)).first()
        if existing is not None:
            return existing

        entry = Suppression(kind=kind, value=normalized, reason=reason)
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def add_for_lead(
        self, lead_email: str | None, lead_domain: str | None, reason: str
    ) -> list[Suppression]:
        added = []
        if lead_email:
            added.append(await self.add(SuppressionKind.EMAIL, lead_email, reason))
        if lead_domain:
            added.append(await self.add(SuppressionKind.DOMAIN, lead_domain, reason))
        return added

    async def remove(self, suppression_id: int) -> bool:
        result = await self.session.execute(
            delete(Suppression).where(Suppression.id == suppression_id)
        )
        return rowcount(result) > 0
