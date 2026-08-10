import pytest

from app.normalization import normalize_city, normalize_country


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Finland", "FI"),
        ("finland", "FI"),
        ("FI", "FI"),
        ("fi", "FI"),
        ("Suomi", "FI"),
        ("United Kingdom", "GB"),
        ("Atlantis", "Atlantis"),
        (None, None),
    ],
)
def test_normalize_country(value: str | None, expected: str | None) -> None:
    assert normalize_country(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("HELSINKI", "Helsinki"),
        ("helsinki", "Helsinki"),
        ("  Helsinki ", "Helsinki"),
        ("s-Hertogenbosch", "s-Hertogenbosch"),
        (None, None),
    ],
)
def test_normalize_city(value: str | None, expected: str | None) -> None:
    assert normalize_city(value) == expected
