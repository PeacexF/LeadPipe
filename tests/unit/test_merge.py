from datetime import UTC, datetime, timedelta

import pytest

from app.deduplication import Candidate, merge
from app.domain import NormalizedLead, SourceRef

EARLY = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
LATE = EARLY + timedelta(days=1)


def candidate(
    origin: str,
    priority: int = 0,
    collected_at: datetime = EARLY,
    source: str = "example_csv",
    **fields: str | None,
) -> Candidate:
    lead = NormalizedLead(
        source=SourceRef(name=source),
        collected_at=collected_at,
        **fields,  # type: ignore[arg-type]
    )
    return Candidate(lead=lead, origin=origin, priority=priority)


def test_non_null_beats_null() -> None:
    merged = merge(
        [
            candidate("rec-1", company_name="Example", email=None),
            candidate("rec-2", company_name=None, email="contact@example.com"),
        ]
    )
    assert merged.lead.company_name == "Example"
    assert merged.lead.email == "contact@example.com"


def test_field_origins_are_recorded() -> None:
    merged = merge(
        [
            candidate("rec-1", company_name="Example"),
            candidate("rec-2", email="contact@example.com"),
        ]
    )
    assert merged.origins["company_name"] == "rec-1"
    assert merged.origins["email"] == "rec-2"
    assert set(merged.contributors) == {"rec-1", "rec-2"}


def test_source_priority_wins_over_recency() -> None:
    merged = merge(
        [
            candidate("rec-1", priority=10, collected_at=EARLY, company_name="Authoritative"),
            candidate("rec-2", priority=0, collected_at=LATE, company_name="Scraped"),
        ]
    )
    assert merged.lead.company_name == "Authoritative"
    assert merged.origins["company_name"] == "rec-1"


def test_recency_breaks_equal_priority() -> None:
    merged = merge(
        [
            candidate("rec-1", collected_at=EARLY, company_name="Old Name"),
            candidate("rec-2", collected_at=LATE, company_name="New Name"),
        ]
    )
    assert merged.lead.company_name == "New Name"


def test_website_and_domain_come_from_the_same_record() -> None:
    merged = merge(
        [
            candidate(
                "rec-1", priority=5, website="https://example.com", website_domain="example.com"
            ),
            candidate("rec-2", website="https://other.test", website_domain="other.test"),
        ]
    )
    assert merged.lead.website == "https://example.com"
    assert merged.lead.website_domain == "example.com"
    assert merged.origins["website_domain"] == "rec-1"


def test_collected_at_is_the_most_recent_sighting() -> None:
    merged = merge(
        [
            candidate("rec-1", collected_at=EARLY, company_name="Example"),
            candidate("rec-2", collected_at=LATE, email="contact@example.com"),
        ]
    )
    assert merged.lead.collected_at == LATE


def test_merge_is_order_independent() -> None:
    a = candidate("rec-1", priority=1, company_name="Example", email=None)
    b = candidate("rec-2", company_name="Other", email="contact@example.com")
    assert merge([a, b]) == merge([b, a])


def test_merge_requires_candidates() -> None:
    with pytest.raises(ValueError):
        merge([])
