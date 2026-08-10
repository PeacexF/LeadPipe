import pytest

from app.normalization import extract_domain, normalize_url


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("example.com", "https://example.com"),
        ("www.example.com/", "https://example.com"),
        ("https://example.com", "https://example.com"),
        ("HTTPS://WWW.Example.COM/", "https://example.com"),
        ("https://example.com:443/about", "https://example.com/about"),
        ("http://example.com:80", "http://example.com"),
        ("https://example.com:8080/x", "https://example.com:8080/x"),
        ("https://example.com/About/", "https://example.com/About"),
        ("https://example.com/#team", "https://example.com"),
        ("https://example.com/?utm_source=ads&id=7", "https://example.com?id=7"),
        ("https://example.com/?b=2&a=1", "https://example.com?a=1&b=2"),
        ("   ", None),
        (None, None),
    ],
)
def test_normalize_url(value: str | None, expected: str | None) -> None:
    assert normalize_url(value) == expected


@pytest.mark.parametrize(
    "value", ["mailto:a@example.com", "ftp://example.com", "not a url", "n/a", "example"]
)
def test_unusable_urls_are_kept_verbatim(value: str) -> None:
    assert normalize_url(value) == value


def test_variants_converge() -> None:
    variants = ["example.com", "www.example.com/", "https://www.example.com", "HTTP://example.com"]
    assert len({extract_domain(normalize_url(v)) for v in variants}) == 1


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://example.com/about", "example.com"),
        ("https://shop.example.com", "shop.example.com"),
        ("not a url", None),
        (None, None),
    ],
)
def test_extract_domain(value: str | None, expected: str | None) -> None:
    assert extract_domain(value) == expected
