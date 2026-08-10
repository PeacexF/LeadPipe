from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://leadpipe:leadpipe@localhost:5432/leadpipe"
    config_path: str = "examples/configs/csv.yaml"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    leadpipe_api_key: str | None = None
    cors_origins: str = ""
    default_page_size: int = 50
    max_page_size: int = 200
    log_level: str = "INFO"
    log_format: str = "console"

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
