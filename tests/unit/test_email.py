import pytest

from app.normalization import normalize_email


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (" CONTACT@EXAMPLE.COM ", "contact@example.com"),
        ("Contact@Example.com", "contact@example.com"),
        ("mailto:contact@example.com", "contact@example.com"),
        ("<contact@example.com>", "contact@example.com"),
        ("   ", None),
        (None, None),
    ],
)
def test_normalize_email(value: str | None, expected: str | None) -> None:
    assert normalize_email(value) == expected


def test_malformed_email_is_kept_not_dropped() -> None:
    assert normalize_email("Not An Email") == "not an email"
