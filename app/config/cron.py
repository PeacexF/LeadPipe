from apscheduler.triggers.cron import CronTrigger

# POSIX cron counts 0 as Sunday; APScheduler counts 0 as Monday. Names are unambiguous.
POSIX_DAYS = {
    "0": "sun",
    "1": "mon",
    "2": "tue",
    "3": "wed",
    "4": "thu",
    "5": "fri",
    "6": "sat",
    "7": "sun",
}

FIELDS = 5


def build_trigger(expression: str, timezone: str = "UTC") -> CronTrigger:
    parts = expression.split()
    if len(parts) != FIELDS:
        raise ValueError(f"expected {FIELDS} fields, got {len(parts)}")
    minute, hour, day, month, day_of_week = parts
    return CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=translate_day_of_week(day_of_week),
        timezone=timezone,
    )


def translate_day_of_week(field: str) -> str:
    return ",".join(_token(token) for token in field.split(","))


def _token(token: str) -> str:
    value, separator, step = token.partition("/")
    suffix = f"/{step}" if separator else ""

    if "-" in value:
        start, _, end = value.partition("-")
        return f"{_day(start)}-{_day(end)}{suffix}"
    return f"{_day(value)}{suffix}"


def _day(value: str) -> str:
    cleaned = value.strip().lower()
    return POSIX_DAYS.get(cleaned, cleaned)
