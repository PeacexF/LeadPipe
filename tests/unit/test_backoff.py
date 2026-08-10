import pytest

from app.jobs.queue import BASE_BACKOFF_SECONDS, MAX_BACKOFF_SECONDS, backoff_seconds


@pytest.mark.parametrize("attempts", [1, 2, 3, 5, 10, 50])
def test_backoff_stays_within_bounds(attempts: int) -> None:
    delay = backoff_seconds(attempts)
    assert BASE_BACKOFF_SECONDS / 2 <= delay <= MAX_BACKOFF_SECONDS


def test_backoff_grows_with_attempts() -> None:
    delays = [backoff_seconds(attempt, jitter=1.0) for attempt in (1, 2, 3, 4)]
    assert delays == sorted(delays)
    assert delays[0] < delays[-1]


def test_backoff_is_capped() -> None:
    assert backoff_seconds(99, jitter=1.0) == MAX_BACKOFF_SECONDS


def test_jitter_spreads_retries() -> None:
    assert backoff_seconds(3, jitter=0.0) < backoff_seconds(3, jitter=1.0)
