import pytest

from app.domain import NormalizedLead, SourceRef
from app.validation import ValidationStatus, validate_lead
from app.validation.rules import (
    validate_company_name,
    validate_email_field,
    validate_phone_field,
    validate_url_field,
)

SOURCE = SourceRef(name="example_csv", url="https://example-directory.test/a")


def make_lead(
    company_name: str | None = None,
    email: str | None = None,
    website: str | None = None,
    phone: str | None = None,
) -> NormalizedLead:
    return NormalizedLead(
        source=SOURCE,
        company_name=company_name,
        email=email,
        website=website,
        phone=phone,
    )


@pytest.mark.parametrize(
    ("value", "status"),
    [
        ("contact@example.com", ValidationStatus.VALID),
        ("not an email", ValidationStatus.INVALID),
        ("contact@", ValidationStatus.INVALID),
        ("@example.com", ValidationStatus.INVALID),
        (None, ValidationStatus.UNKNOWN),
    ],
)
def test_validate_email(value: str | None, status: ValidationStatus) -> None:
    assert validate_email_field(value).status is status


@pytest.mark.parametrize(
    ("value", "status"),
    [
        ("https://example.com", ValidationStatus.VALID),
        ("https://example.com/about", ValidationStatus.VALID),
        ("not a url", ValidationStatus.INVALID),
        ("ftp://example.com", ValidationStatus.INVALID),
        (None, ValidationStatus.UNKNOWN),
    ],
)
def test_validate_url(value: str | None, status: ValidationStatus) -> None:
    assert validate_url_field(value).status is status


@pytest.mark.parametrize(
    ("value", "status"),
    [
        ("+358401234567", ValidationStatus.VALID),
        ("040-1234567", ValidationStatus.INVALID),
        ("call us", ValidationStatus.INVALID),
        (None, ValidationStatus.UNKNOWN),
    ],
)
def test_validate_phone(value: str | None, status: ValidationStatus) -> None:
    assert validate_phone_field(value).status is status


def test_missing_company_name_is_invalid_not_unknown() -> None:
    assert validate_company_name(None).status is ValidationStatus.INVALID
    assert validate_company_name("Example Services").status is ValidationStatus.VALID


def test_absent_email_does_not_make_a_lead_invalid() -> None:
    result = validate_lead(make_lead(company_name="Example", phone="+358401234567"))
    assert result.fields["email"].status is ValidationStatus.UNKNOWN
    assert result.status is ValidationStatus.VALID


def test_bad_email_with_good_phone_reports_per_field() -> None:
    result = validate_lead(
        make_lead(company_name="Example", email="not an email", phone="+358401234567")
    )
    assert result.fields["email"].status is ValidationStatus.INVALID
    assert result.fields["email"].reason == "syntax"
    assert result.fields["phone"].status is ValidationStatus.VALID
    assert result.status is ValidationStatus.INVALID
    assert result.invalid_fields == ("email",)


def test_nothing_verifiable_rolls_up_to_unknown() -> None:
    lead = NormalizedLead(source=SourceRef(name="example_csv"), company_name="Example")
    assert validate_lead(lead).status is ValidationStatus.UNKNOWN


def test_source_url_is_validated() -> None:
    lead = NormalizedLead(source=SourceRef(name="example_csv", url="nope"), company_name="Example")
    result = validate_lead(lead)
    assert result.fields["source_url"].status is ValidationStatus.INVALID
    assert result.status is ValidationStatus.INVALID
