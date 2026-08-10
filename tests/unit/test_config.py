from pathlib import Path

import pytest

from app.config import ConfigError, interpolate, load_config


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(body)
    return path


def test_loads_sources(tmp_path: Path) -> None:
    config = load_config(
        write(
            tmp_path,
            """
            defaults:
              region: FI
            sources:
              - name: example_csv
                type: csv
                path: ./data.csv
                mapping:
                  company_name: name
            """,
        )
    )
    assert config.defaults.region == "FI"
    assert config.source("example_csv").options["path"] == "./data.csv"
    assert config.source("example_csv").mapping == {"company_name": "name"}


def test_disabled_sources_are_excluded(tmp_path: Path) -> None:
    config = load_config(
        write(
            tmp_path,
            """
            sources:
              - name: active
                type: csv
              - name: paused
                type: csv
                enabled: false
            """,
        )
    )
    assert [s.name for s in config.enabled_sources()] == ["active"]


def test_duplicate_source_names_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="duplicate source names"):
        load_config(
            write(
                tmp_path,
                """
                sources:
                  - name: same
                    type: csv
                  - name: same
                    type: api
                """,
            )
        )


def test_missing_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml")


def test_invalid_yaml_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config(write(tmp_path, "sources: [unclosed"))


def test_unknown_source_raises(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, "sources: []"))
    with pytest.raises(KeyError):
        config.source("nope")


def test_env_interpolation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEADPIPE_TEST_TOKEN", "secret")
    assert interpolate("Bearer ${LEADPIPE_TEST_TOKEN}") == "Bearer secret"
    assert interpolate({"a": ["${LEADPIPE_TEST_TOKEN}"]}) == {"a": ["secret"]}


def test_env_interpolation_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEADPIPE_MISSING", raising=False)
    assert interpolate("${LEADPIPE_MISSING:-fallback}") == "fallback"


def test_env_interpolation_requires_a_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEADPIPE_MISSING", raising=False)
    with pytest.raises(ConfigError, match="not set"):
        interpolate("${LEADPIPE_MISSING}")


def test_shipped_example_config_is_valid() -> None:
    config = load_config(Path("examples/configs/csv.yaml"))
    source = config.source("example_csv")
    assert source.type == "csv"
    assert Path(source.options["path"]).is_file()
