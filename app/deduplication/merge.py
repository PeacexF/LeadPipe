from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.domain.models import NormalizedLead

SINGLE_FIELDS = (
    "company_name",
    "contact_name",
    "email",
    "phone",
    "address",
    "city",
    "country",
)
# derived from one another, so they must come from the same candidate
WEBSITE_FIELDS = ("website", "website_domain")


@dataclass(frozen=True, slots=True)
class Candidate:
    lead: NormalizedLead
    origin: str
    priority: int = 0


@dataclass(frozen=True, slots=True)
class MergedLead:
    lead: NormalizedLead
    origins: Mapping[str, str] = field(default_factory=dict)

    @property
    def contributors(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(self.origins.values()))


def merge(candidates: Sequence[Candidate]) -> MergedLead:
    if not candidates:
        raise ValueError("merge() requires at least one candidate")

    ranked = sorted(candidates, key=_rank)
    values: dict[str, Any] = {}
    origins: dict[str, str] = {}

    for name in SINGLE_FIELDS:
        winner = _first_with(ranked, name)
        if winner is not None:
            values[name] = getattr(winner.lead, name)
            origins[name] = winner.origin

    website_winner = _first_with(ranked, "website")
    if website_winner is not None:
        for name in WEBSITE_FIELDS:
            values[name] = getattr(website_winner.lead, name)
            origins[name] = website_winner.origin

    extra: dict[str, Any] = {}
    for candidate in reversed(ranked):
        extra.update(candidate.lead.extra)

    lead = NormalizedLead(
        source=ranked[0].lead.source,
        collected_at=max(candidate.lead.collected_at for candidate in candidates),
        extra=extra,
        **values,
    )
    return MergedLead(lead=lead, origins=origins)


def _rank(candidate: Candidate) -> tuple[int, float, int, int, str]:
    # highest priority, then most recent, then most complete, then oldest origin
    return (
        -candidate.priority,
        -candidate.lead.collected_at.timestamp(),
        -_filled(candidate),
        *_origin_key(candidate.origin),
    )


def _origin_key(origin: str) -> tuple[int, str]:
    # record ids are numeric strings, so "11" must not sort before "3"
    return (0, origin.zfill(20)) if origin.isdigit() else (1, origin)


def _filled(candidate: Candidate) -> int:
    fields = (*SINGLE_FIELDS, *WEBSITE_FIELDS)
    return sum(getattr(candidate.lead, name) is not None for name in fields)


def _first_with(ranked: Sequence[Candidate], name: str) -> Candidate | None:
    return next((c for c in ranked if getattr(c.lead, name) is not None), None)
