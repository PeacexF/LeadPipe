import pytest

from app.fetch import FetchPolicy, UnsafeUrlError, ensure_safe_url, is_public_address

PUBLIC = FetchPolicy()
PRIVATE_OK = FetchPolicy(allow_private_hosts=True)


def resolves_to(*addresses: str):  # type: ignore[no-untyped-def]
    return lambda host: list(addresses)


@pytest.mark.parametrize(
    ("address", "public"),
    [
        ("93.184.216.34", True),
        ("2606:2800:220:1:248:1893:25c8:1946", True),
        ("127.0.0.1", False),
        ("::1", False),
        ("10.0.0.5", False),
        ("192.168.1.10", False),
        ("172.16.0.1", False),
        ("169.254.169.254", False),
        ("0.0.0.0", False),
        ("224.0.0.1", False),
        ("not-an-ip", False),
    ],
)
def test_is_public_address(address: str, public: bool) -> None:
    assert is_public_address(address) is public


@pytest.mark.parametrize("url", ["ftp://example.com", "file:///etc/passwd", "mailto:a@b.com"])
async def test_only_http_schemes_are_allowed(url: str) -> None:
    with pytest.raises(UnsafeUrlError, match="scheme not allowed"):
        await ensure_safe_url(url, PUBLIC, resolves_to("93.184.216.34"))


async def test_url_without_host_is_rejected() -> None:
    with pytest.raises(UnsafeUrlError, match="no host"):
        await ensure_safe_url("http:///path", PUBLIC, resolves_to("93.184.216.34"))


async def test_public_host_is_allowed() -> None:
    url = "https://example.com/companies"
    assert await ensure_safe_url(url, PUBLIC, resolves_to("93.184.216.34")) == url


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "10.0.0.5", "169.254.169.254", "192.168.0.1", "::1"]
)
async def test_private_targets_are_blocked(address: str) -> None:
    with pytest.raises(UnsafeUrlError, match="non-public address"):
        await ensure_safe_url("https://internal.test", PUBLIC, resolves_to(address))


async def test_a_host_resolving_to_both_is_blocked() -> None:
    with pytest.raises(UnsafeUrlError, match="non-public address"):
        await ensure_safe_url(
            "https://sneaky.test", PUBLIC, resolves_to("93.184.216.34", "169.254.169.254")
        )


async def test_unresolvable_host_is_rejected() -> None:
    def boom(host: str) -> list[str]:
        raise OSError("nxdomain")

    with pytest.raises(UnsafeUrlError, match="cannot resolve"):
        await ensure_safe_url("https://nope.test", PUBLIC, boom)

    with pytest.raises(UnsafeUrlError, match="cannot resolve"):
        await ensure_safe_url("https://nope.test", PUBLIC, resolves_to())


async def test_private_hosts_can_be_opted_into() -> None:
    url = "http://localhost:8001/leads"
    assert await ensure_safe_url(url, PRIVATE_OK, resolves_to("127.0.0.1")) == url
