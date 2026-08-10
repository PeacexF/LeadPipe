from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://leadpipe:leadpipe@localhost:5432/leadpipe"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    leadpipe_api_key: str | None = None
    log_level: str = "INFO"
    log_format: str = "console"


@lru_cache
def get_settings() -> Settings:
    return Settings()
