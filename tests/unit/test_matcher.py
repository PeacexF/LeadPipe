from datetime import UTC, datetime

from app.deduplication import MatchRule, match
from app.domain import RawRecord, SourceRef
from app.normalization import normalize_record

COLLECTED_AT = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)


def lead(source: str = "example_csv", **fields: str | None):  # type: ignore[no-untyped-def]
    return normalize_record(
        RawRecord(source=SourceRef(name=source), fields=fields, collected_at=COLLECTED_AT)
    )


def test_plan_example_merges_on_email() -> None:
    a = lead(company_name="Example Services", email="contact@example.com")
    b = lead(source="example_api", company_name="EXAMPLE SERVICES LTD", email="CONTACT@EXAMPLE.COM")

    result = match(a, b)
    assert result is not None
    assert result.rule is MatchRule.EMAIL
    assert result.confidence == 1.0
    assert result.auto_merge


def test_website_variants_match() -> None:
    a = lead(company_name="Example", website="www.example.com/")
    b = lead(company_name="Example", website="https://example.com/about")

    result = match(a, b)
    assert result is not None
    assert result.rule is MatchRule.WEBSITE
    assert result.auto_merge


def test_phone_variants_match() -> None:
    a = lead(company_name="Example", phone="+358 40 123 4567")
    b = lead(company_name="Example", phone="040 123 4567", country="Finland")

    result = match(a, b)
    assert result is not None
    assert result.rule is MatchRule.PHONE
    assert result.auto_merge


def test_similar_names_in_same_city_need_review() -> None:
    a = lead(company_name="Example Services Oy", city="Helsinki", country="FI")
    b = lead(company_name="Example Service", city="HELSINKI", country="Finland")

    result = match(a, b)
    assert result is not None
    assert result.rule is MatchRule.NAME_LOCATION
    assert result.needs_review
    assert not result.auto_merge


def test_same_name_different_city_does_not_match() -> None:
    a = lead(company_name="Example Services Oy", city="Helsinki", country="FI")
    b = lead(company_name="Example Services Oy", city="Tampere", country="FI")

    assert match(a, b) is None


def test_external_id_matches_only_within_a_source() -> None:
    a = lead(company_name="Example", external_id="A-1")
    b = lead(company_name="Other", external_id="A-1")
    assert match(a, b) is not None

    c = lead(source="example_api", company_name="Other", external_id="A-1")
    assert match(a, c) is None


def test_unrelated_leads_do_not_match() -> None:
    a = lead(
        company_name="Example Services",
        email="contact@example.com",
        phone="+358401234567",
        city="Helsinki",
        country="FI",
    )
    b = lead(
        company_name="Nordic Logistics",
        email="hello@nordic-logistics.test",
        phone="+358401111111",
        city="Helsinki",
        country="FI",
    )
    assert match(a, b) is None


def test_shared_garbage_values_do_not_match() -> None:
    a = lead(company_name="Example Services", email="n/a", phone="call us")
    b = lead(company_name="Nordic Logistics", email="n/a", phone="call us")
    assert match(a, b) is None


def test_missing_location_blocks_the_name_rule() -> None:
    a = lead(company_name="Example Services Oy")
    b = lead(company_name="Example Services Oy")
    assert match(a, b) is None
