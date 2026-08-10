import asyncio

from app.fetch import DomainThrottle


async def test_first_request_is_not_delayed() -> None:
    throttle = DomainThrottle(min_interval=0.05)
    assert await throttle.wait("example.com") == 0.0


async def test_second_request_to_the_same_host_waits() -> None:
    throttle = DomainThrottle(min_interval=0.05)
    await throttle.wait("example.com")

    start = asyncio.get_running_loop().time()
    await throttle.wait("example.com")
    assert asyncio.get_running_loop().time() - start >= 0.04


async def test_hosts_are_throttled_independently() -> None:
    throttle = DomainThrottle(min_interval=0.05)
    await throttle.wait("example.com")
    assert await throttle.wait("other.test") == 0.0


async def test_crawl_delay_can_widen_the_interval() -> None:
    throttle = DomainThrottle(min_interval=0.0)
    await throttle.wait("example.com", min_interval=0.05)

    start = asyncio.get_running_loop().time()
    await throttle.wait("example.com", min_interval=0.05)
    assert asyncio.get_running_loop().time() - start >= 0.04


async def test_no_interval_means_no_waiting() -> None:
    throttle = DomainThrottle(min_interval=0.0)
    for _ in range(5):
        assert await throttle.wait("example.com") == 0.0


def test_policy_is_built_from_source_options() -> None:
    from app.fetch import FetchPolicy

    policy = FetchPolicy.from_options(
        {
            "timeout": 3.0,
            "requests_per_second": 4,
            "max_response_bytes": 1024,
            "respect_robots": False,
            "path": "./ignored.csv",
            "mapping": {"company_name": "name"},
        }
    )

    assert policy.timeout == 3.0
    assert policy.min_interval == 0.25
    assert policy.max_response_bytes == 1024
    assert policy.respect_robots is False
    assert policy.max_redirects == FetchPolicy().max_redirects
