import pytest

from app.normalization import normalize_phone


@pytest.mark.parametrize(
    ("value", "region", "expected"),
    [
        ("+358401234567", None, "+358401234567"),
        ("+358 40 123 4567", None, "+358401234567"),
        ("(040) 123 4567", "FI", "+358401234567"),
        ("040-1234567", "FI", "+358401234567"),
        ("   ", None, None),
        (None, None, None),
    ],
)
def test_normalize_phone(value: str | None, region: str | None, expected: str | None) -> None:
    assert normalize_phone(value, region) == expected


@pytest.mark.parametrize("value", ["12", "call us", "040-1234567"])
def test_unparseable_phone_is_kept_not_dropped(value: str) -> None:
    assert normalize_phone(value) == value
