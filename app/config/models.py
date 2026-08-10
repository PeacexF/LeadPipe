from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Defaults(BaseModel):
    region: str | None = None


class SourceConfig(BaseModel):
    # type-specific keys stay in model_extra and are parsed by the adapter
    model_config = ConfigDict(extra="allow")

    name: str
    type: str
    enabled: bool = True
    priority: int = 0
    region: str | None = None
    mapping: dict[str, str] = Field(default_factory=dict)

    @property
    def options(self) -> dict[str, Any]:
        return dict(self.model_extra or {})


class AppConfig(BaseModel):
    defaults: Defaults = Field(default_factory=Defaults)
    sources: list[SourceConfig] = Field(default_factory=list)

    @field_validator("sources")
    @classmethod
    def names_must_be_unique(cls, sources: list[SourceConfig]) -> list[SourceConfig]:
        names = [source.name for source in sources]
        duplicates = {name for name in names if names.count(name) > 1}
        if duplicates:
            raise ValueError(f"duplicate source names: {', '.join(sorted(duplicates))}")
        return sources

    def source(self, name: str) -> SourceConfig:
        for source in self.sources:
            if source.name == name:
                return source
        raise KeyError(f"unknown source: {name}")

    def enabled_sources(self) -> list[SourceConfig]:
        return [source for source in self.sources if source.enabled]
