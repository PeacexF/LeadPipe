import asyncio

import httpx
import pytest

from app.fetch import (
    Fetcher,
    FetchError,
    FetchPolicy,
    ResponseTooLarge,
    RobotsDisallowed,
    TooManyRedirects,
    UnsafeUrlError,
)

ROBOTS_ALLOW_ALL = "User-agent: *\nAllow: /\n"
ROBOTS_DENY_PRIVATE = "User-agent: *\nDisallow: /private\nCrawl-delay: 0\n"

PUBLIC_IP = ["93.184.216.34"]


def policy(**overrides: object) -> FetchPolicy:
    defaults: dict[str, object] = {"requests_per_second": 0, "retries": 0, "backoff_base": 0.0}
    return FetchPolicy(**{**defaults, **overrides})  # type: ignore[arg-type]


def build(handler, **overrides: object) -> Fetcher:  # type: ignore[no-untyped-def]
    return Fetcher(
        policy=policy(**overrides),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False),
        resolver=lambda host: list(PUBLIC_IP),
    )


def routes(**paths: httpx.Response):  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return paths.get("robots", httpx.Response(200, text=ROBOTS_ALLOW_ALL))
        return paths.get("page", httpx.Response(200, text="<html>ok</html>"))

    return handler


async def test_fetches_a_page() -> None:
    async with build(routes()) as fetcher:
        response = await fetcher.get("https://example.com/companies")

    assert response.status_code == 200
    assert "ok" in response.text


async def test_sends_a_descriptive_user_agent() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("user-agent", ""))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_ALLOW_ALL)
        return httpx.Response(200, text="ok")

    fetcher = Fetcher(
        policy=policy(contact="https://example.com/bot"),
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            headers={"User-Agent": policy(contact="https://example.com/bot").user_agent},
        ),
        resolver=lambda host: list(PUBLIC_IP),
    )
    async with fetcher:
        await fetcher.get("https://example.com/x")

    assert all(agent.startswith("LeadPipe/") for agent in seen)
    assert "https://example.com/bot" in seen[0]


async def test_robots_disallow_blocks_the_request() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_DENY_PRIVATE)
        return httpx.Response(200, text="secret")

    async with build(handler) as fetcher:
        with pytest.raises(RobotsDisallowed):
            await fetcher.get("https://example.com/private/list")

        allowed = await fetcher.get("https://example.com/public")

    assert allowed.status_code == 200
    assert "/private/list" not in requested


async def test_robots_is_fetched_once_per_origin() -> None:
    hits = {"robots": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            hits["robots"] += 1
            return httpx.Response(200, text=ROBOTS_ALLOW_ALL)
        return httpx.Response(200, text="ok")

    async with build(handler) as fetcher:
        for path in ("/a", "/b", "/c"):
            await fetcher.get(f"https://example.com{path}")

    assert hits["robots"] == 1


async def test_unreachable_robots_denies_rather_than_allows() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(503)
        return httpx.Response(200, text="ok")

    async with build(handler) as fetcher:
        with pytest.raises(RobotsDisallowed):
            await fetcher.get("https://example.com/page")


async def test_missing_robots_allows() -> None:
    async with build(routes(robots=httpx.Response(404))) as fetcher:
        assert (await fetcher.get("https://example.com/page")).status_code == 200


async def test_robots_can_be_turned_off() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            raise AssertionError("robots.txt should not be fetched")
        return httpx.Response(200, text="ok")

    async with build(handler, respect_robots=False) as fetcher:
        assert (await fetcher.get("https://example.com/page")).status_code == 200


async def test_oversized_body_is_aborted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_ALLOW_ALL)
        return httpx.Response(200, content=b"x" * 5000)

    async with build(handler, max_response_bytes=1000) as fetcher:
        with pytest.raises(ResponseTooLarge):
            await fetcher.get("https://example.com/huge")


async def test_oversized_content_length_is_rejected_before_reading() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_ALLOW_ALL)
        return httpx.Response(200, content=b"x" * 10, headers={"content-length": "999999999"})

    async with build(handler, max_response_bytes=1000) as fetcher:
        with pytest.raises(ResponseTooLarge, match="declares"):
            await fetcher.get("https://example.com/huge")


async def test_redirects_are_followed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_ALLOW_ALL)
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "https://example.com/new"})
        return httpx.Response(200, text="arrived")

    async with build(handler) as fetcher:
        response = await fetcher.get("https://example.com/old")

    assert response.status_code == 200
    assert response.text == "arrived"


async def test_redirect_to_a_private_address_is_blocked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_ALLOW_ALL)
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data"})

    def resolver(host: str) -> list[str]:
        return ["169.254.169.254"] if host == "169.254.169.254" else list(PUBLIC_IP)

    fetcher = Fetcher(
        policy=policy(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False),
        resolver=resolver,
    )
    async with fetcher:
        with pytest.raises(UnsafeUrlError):
            await fetcher.get("https://example.com/redirect")


async def test_redirect_loops_are_capped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_ALLOW_ALL)
        return httpx.Response(302, headers={"location": "https://example.com/loop"})

    async with build(handler, max_redirects=3) as fetcher:
        with pytest.raises(TooManyRedirects):
            await fetcher.get("https://example.com/loop")


async def test_server_errors_are_retried_then_reported() -> None:
    attempts = {"page": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_ALLOW_ALL)
        attempts["page"] += 1
        return httpx.Response(503)

    async with build(handler, retries=2) as fetcher:
        with pytest.raises(FetchError):
            await fetcher.get("https://example.com/flaky")

    assert attempts["page"] == 3


async def test_a_retry_can_succeed() -> None:
    attempts = {"page": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_ALLOW_ALL)
        attempts["page"] += 1
        if attempts["page"] == 1:
            return httpx.Response(500)
        return httpx.Response(200, text="recovered")

    async with build(handler, retries=2) as fetcher:
        response = await fetcher.get("https://example.com/flaky")

    assert response.text == "recovered"
    assert attempts["page"] == 2


async def test_client_errors_are_returned_not_retried() -> None:
    attempts = {"page": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_ALLOW_ALL)
        attempts["page"] += 1
        return httpx.Response(404)

    async with build(handler, retries=2) as fetcher:
        response = await fetcher.get("https://example.com/missing")

    assert response.status_code == 404
    assert attempts["page"] == 1


async def test_requests_are_rate_limited_per_host() -> None:
    async with build(routes(), requests_per_second=20) as fetcher:
        start = asyncio.get_running_loop().time()
        for path in ("/a", "/b", "/c"):
            await fetcher.get(f"https://example.com{path}")
        elapsed = asyncio.get_running_loop().time() - start

    assert elapsed >= 0.10
