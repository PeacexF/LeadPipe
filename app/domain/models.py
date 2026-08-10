from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

LEAD_FIELDS = (
    "company_name",
    "contact_name",
    "website",
    "email",
    "phone",
    "address",
    "city",
    "country",
)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class SourceRef:
    name: str
    url: str | None = None


@dataclass(frozen=True, slots=True)
class RawRecord:
    source: SourceRef
    fields: Mapping[str, str | None]
    raw: Mapping[str, Any] = field(default_factory=dict)
    collected_at: datetime = field(default_factory=_now)


@dataclass(frozen=True, slots=True)
class NormalizedLead:
    source: SourceRef
    collected_at: datetime = field(default_factory=_now)
    company_name: str | None = None
    contact_name: str | None = None
    website: str | None = None
    website_domain: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    city: str | None = None
    country: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)
