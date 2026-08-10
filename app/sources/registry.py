from collections.abc import Callable

from app.config.models import SourceConfig
from app.sources.base import Source, SourceError

SourceFactory = Callable[[SourceConfig], Source]

_REGISTRY: dict[str, SourceFactory] = {}


def register(type_name: str) -> Callable[[SourceFactory], SourceFactory]:
    def decorator(factory: SourceFactory) -> SourceFactory:
        _REGISTRY[type_name] = factory
        return factory

    return decorator


def build_source(config: SourceConfig) -> Source:
    factory = _REGISTRY.get(config.type)
    if factory is None:
        known = ", ".join(sorted(_REGISTRY)) or "none"
        raise SourceError(f"unknown source type '{config.type}' (registered: {known})")
    return factory(config)


def registered_types() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))
