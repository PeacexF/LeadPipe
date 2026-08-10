import os
import re
from pathlib import Path
from typing import Any

import yaml

from app.config.models import AppConfig

_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


class ConfigError(Exception):
    pass


def load_config(path: str | Path) -> AppConfig:
    file = Path(path)
    if not file.is_file():
        raise ConfigError(f"config file not found: {file}")
    try:
        data = yaml.safe_load(file.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {file}: {exc}") from exc

    try:
        return AppConfig.model_validate(interpolate(data))
    except ValueError as exc:
        raise ConfigError(f"invalid config in {file}: {exc}") from exc


def interpolate(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV_REF.sub(_replace, value)
    if isinstance(value, dict):
        return {key: interpolate(item) for key, item in value.items()}
    if isinstance(value, list):
        return [interpolate(item) for item in value]
    return value


def _replace(match: re.Match[str]) -> str:
    name, default = match.group(1), match.group(2)
    resolved = os.getenv(name, default)
    if resolved is None:
        raise ConfigError(f"environment variable {name} is not set")
    return resolved
