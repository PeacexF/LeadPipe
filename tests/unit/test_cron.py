from datetime import UTC, datetime

import pytest

from app.config.cron import build_trigger, translate_day_of_week

MONDAY = datetime(2026, 8, 10, 7, 0, tzinfo=UTC)


def fires_at(expression: str, after: datetime = MONDAY) -> datetime:
    fire_time = build_trigger(expression).get_next_fire_time(None, after)
    assert fire_time is not None
    return fire_time


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("*", "*"),
        ("0", "sun"),
        ("1", "mon"),
        ("6", "sat"),
        ("7", "sun"),
        ("1-5", "mon-fri"),
        ("0,6", "sun,sat"),
        ("mon", "mon"),
        ("mon-fri", "mon-fri"),
        ("*/2", "*/2"),
    ],
)
def test_day_of_week_uses_posix_numbering(field: str, expected: str) -> None:
    assert translate_day_of_week(field) == expected


@pytest.mark.parametrize(
    ("expression", "weekday"),
    [
        ("30 6 * * 0", "Sunday"),
        ("30 6 * * 1", "Monday"),
        ("30 6 * * 5", "Friday"),
        ("30 6 * * 6", "Saturday"),
        ("30 6 * * 7", "Sunday"),
    ],
)
def test_numeric_days_match_crontab(expression: str, weekday: str) -> None:
    assert fires_at(expression).strftime("%A") == weekday


def test_weekday_range_skips_the_weekend() -> None:
    saturday = datetime(2026, 8, 15, 7, 0, tzinfo=UTC)
    assert fires_at("30 6 * * 1-5", saturday).strftime("%A") == "Monday"


def test_daily_expression() -> None:
    assert fires_at("0 9 * * *") == datetime(2026, 8, 10, 9, 0, tzinfo=UTC)


@pytest.mark.parametrize("expression", ["", "0 9 * *", "0 9 * * * *", "not a cron"])
def test_malformed_expressions_are_rejected(expression: str) -> None:
    with pytest.raises(ValueError):
        build_trigger(expression)
