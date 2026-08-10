import pytest

from app.deduplication import company_slug, fingerprints, similarity
from app.domain import NormalizedLead, SourceRef

SOURCE = SourceRef(name="example_csv")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Example Services Oy", "example services"),
        ("EXAMPLE SERVICES LTD", "example services"),
        ("Example Services", "example services"),
        ("Example  Services,  Inc.", "example services"),
        ("Example Services Oy Ab", "example services"),
        ("Oy", None),
        (None, None),
    ],
)
def test_company_slug(value: str | None, expected: str | None) -> None:
    assert company_slug(value) == expected


def test_similarity_is_symmetric_and_bounded() -> None:
    assert similarity("example services", "example services") == 1.0
    assert similarity("example services", "totally different") < 0.2
    assert similarity("a", "b") == similarity("b", "a")


def test_similar_names_score_above_threshold() -> None:
    assert similarity("example services", "example service") > 0.7
    assert similarity("example cleaning", "example cleanng") > 0.7


def test_unrelated_names_score_below_threshold() -> None:
    assert similarity("example services", "nordic logistics") < 0.7


def test_fingerprints_ignore_unusable_values() -> None:
    lead = NormalizedLead(
        source=SOURCE,
        email="not an email",
        phone="call us",
        company_name="Example Services Oy",
        city="Helsinki",
        country="FI",
    )
    fp = fingerprints(lead)
    assert fp.email is None
    assert fp.phone is None
    assert fp.name_slug == "example services"
    assert fp.location == "helsinki|fi"


def test_fingerprints_keep_usable_values() -> None:
    lead = NormalizedLead(
        source=SOURCE,
        email="contact@example.com",
        phone="+358401234567",
        website_domain="example.com",
        extra={"external_id": 42},
    )
    fp = fingerprints(lead)
    assert fp.email == "contact@example.com"
    assert fp.phone == "+358401234567"
    assert fp.domain == "example.com"
    assert fp.external_id == "42"
