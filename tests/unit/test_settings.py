import pytest

from app.settings import Settings


def build(**env: str) -> Settings:
    return Settings(_env_file=None, **env)  # type: ignore[arg-type]


def test_blank_retention_days_means_no_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RETENTION_DAYS", "")
    assert build().retention_days is None


def test_retention_days_is_read_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RETENTION_DAYS", "365")
    assert build().retention_days == 365


def test_allowed_origins_ignores_blanks() -> None:
    settings = build(cors_origins=" https://a.test , ,https://b.test ")
    assert settings.allowed_origins == ["https://a.test", "https://b.test"]


def test_no_origins_disables_cors() -> None:
    assert build(cors_origins="").allowed_origins == []
