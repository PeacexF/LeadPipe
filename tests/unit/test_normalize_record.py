from datetime import UTC, datetime

from app.domain import RawRecord, SourceRef
from app.normalization import normalize_record

COLLECTED_AT = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)


def make_record(**fields: str | None) -> RawRecord:
    return RawRecord(
        source=SourceRef(name="example_csv", url="https://example-directory.test/a"),
        fields=fields,
        collected_at=COLLECTED_AT,
    )


def test_normalizes_every_field() -> None:
    lead = normalize_record(
        make_record(
            company_name="  Example Services Oy  ",
            contact_name=" Anna  Virtanen ",
            website="WWW.Example.com/",
            email=" CONTACT@EXAMPLE.COM ",
            phone="040 123 4567",
            address=" Example Street 10 ",
            city="HELSINKI",
            country="Finland",
        )
    )

    assert lead.company_name == "Example Services Oy"
    assert lead.contact_name == "Anna Virtanen"
    assert lead.website == "https://example.com"
    assert lead.website_domain == "example.com"
    assert lead.email == "contact@example.com"
    assert lead.phone == "+358401234567"
    assert lead.city == "Helsinki"
    assert lead.country == "FI"
    assert lead.source.name == "example_csv"
    assert lead.collected_at == COLLECTED_AT


def test_country_supplies_phone_region() -> None:
    lead = normalize_record(make_record(phone="040 123 4567", country="Finland"))
    assert lead.phone == "+358401234567"


def test_default_region_overrides_country() -> None:
    lead = normalize_record(make_record(phone="040 123 4567"), default_region="FI")
    assert lead.phone == "+358401234567"


def test_unmapped_fields_go_to_extra() -> None:
    lead = normalize_record(make_record(company_name="Example", vat_id="FI12345678"))
    assert lead.extra == {"vat_id": "FI12345678"}


def test_missing_fields_are_none() -> None:
    lead = normalize_record(make_record(company_name="Example"))
    assert lead.email is None
    assert lead.phone is None
    assert lead.website is None
    assert lead.website_domain is None


def test_two_sources_converge_on_the_same_values() -> None:
    a = normalize_record(make_record(company_name="Example Services", email="contact@example.com"))
    b = normalize_record(make_record(company_name="EXAMPLE SERVICES", email="CONTACT@EXAMPLE.COM"))
    assert a.email == b.email
