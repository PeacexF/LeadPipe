from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.config import ConfigError, load_config
from app.config.models import SourceConfig
from app.jobs import next_run, trigger_for


def write(tmp_path: Path, schedule: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text("sources:\n  - name: example\n    type: csv\n    path: ./x.csv\n" + schedule)
    return path


def scheduled(cron: str, timezone: str = "UTC") -> SourceConfig:
    return SourceConfig.model_validate(
        {
            "name": "example",
            "type": "csv",
            "schedule": {"enabled": True, "cron": cron, "timezone": timezone},
        }
    )


def test_schedule_is_parsed(tmp_path: Path) -> None:
    config = load_config(
        write(tmp_path, '    schedule:\n      enabled: true\n      cron: "0 9 * * *"\n')
    )
    source = config.source("example")
    assert source.schedule is not None
    assert source.schedule.cron == "0 9 * * *"
    assert source.schedule.timezone == "UTC"
    assert [s.name for s in config.scheduled_sources()] == ["example"]


def test_invalid_cron_is_rejected_at_load(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="invalid cron"):
        load_config(
            write(tmp_path, '    schedule:\n      enabled: true\n      cron: "not a cron"\n')
        )


def test_disabled_schedules_are_not_scheduled(tmp_path: Path) -> None:
    config = load_config(
        write(tmp_path, '    schedule:\n      enabled: false\n      cron: "0 9 * * *"\n')
    )
    assert config.scheduled_sources() == []


def test_sources_without_a_schedule_are_not_scheduled(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, ""))
    assert config.scheduled_sources() == []


def test_disabled_source_is_never_scheduled(tmp_path: Path) -> None:
    config = load_config(
        write(
            tmp_path,
            '    enabled: false\n    schedule:\n      enabled: true\n      cron: "0 9 * * *"\n',
        )
    )
    assert config.scheduled_sources() == []


def test_next_run_is_computed_from_a_fixed_moment() -> None:
    source = scheduled("0 9 * * *")
    after = datetime(2026, 8, 10, 8, 0, tzinfo=UTC)

    assert next_run(source, after) == datetime(2026, 8, 10, 9, 0, tzinfo=UTC)


def test_next_run_rolls_to_the_following_day() -> None:
    source = scheduled("0 9 * * *")
    after = datetime(2026, 8, 10, 9, 30, tzinfo=UTC)

    assert next_run(source, after) == datetime(2026, 8, 11, 9, 0, tzinfo=UTC)


def test_timezone_is_honoured() -> None:
    helsinki = scheduled("0 9 * * *", "Europe/Helsinki")
    after = datetime(2026, 8, 10, 0, 0, tzinfo=UTC)

    fires_at = next_run(helsinki, after)
    assert fires_at is not None
    assert fires_at.astimezone(ZoneInfo("Europe/Helsinki")).hour == 9
    assert fires_at.astimezone(UTC).hour == 6  # summer time offset


def test_weekly_cron_uses_crontab_day_numbering() -> None:
    source = scheduled("30 6 * * 1")  # Monday in crontab
    after = datetime(2026, 8, 10, 7, 0, tzinfo=UTC)  # Monday, just after the fire time

    fires_at = next_run(source, after)
    assert fires_at == datetime(2026, 8, 17, 6, 30, tzinfo=UTC)
    assert fires_at.strftime("%A") == "Monday"


def test_trigger_requires_a_schedule() -> None:
    with pytest.raises(ValueError, match="no schedule"):
        trigger_for(SourceConfig.model_validate({"name": "x", "type": "csv"}))
