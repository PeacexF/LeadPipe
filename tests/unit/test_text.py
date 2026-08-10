import pytest

from app.normalization import clean_text, normalize_company_name


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("  Example Company Ltd.  ", "Example Company Ltd."),
        ("Example\n\tCompany", "Example Company"),
        ("Example   Company", "Example Company"),
        ("   ", None),
        ("", None),
        (None, None),
    ],
)
def test_clean_text(value: str | None, expected: str | None) -> None:
    assert clean_text(value) == expected


def test_company_name_keeps_casing_and_punctuation() -> None:
    assert normalize_company_name("  IBM Nordic Oy  ") == "IBM Nordic Oy"
