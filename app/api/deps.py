from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.models import AppConfig
from app.domain.filters import LeadFilter
from app.settings import Settings
from app.validation import ValidationStatus


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_config(request: Request) -> AppConfig:
    config: AppConfig = request.app.state.config
    return config


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    return factory


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory = get_session_factory(request)
    async with factory() as session:
        yield session


async def require_api_key(
    request: Request,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    expected = get_settings(request).leadpipe_api_key
    if not expected:
        return
    if x_api_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing API key"
        )


def lead_filters(
    source: str | None = None,
    country: str | None = None,
    city: str | None = None,
    validation_status: ValidationStatus | None = None,
) -> LeadFilter:
    return LeadFilter(
        source=source, country=country, city=city, validation_status=validation_status
    )


def page_size(request: Request, limit: int | None = None) -> int:
    settings = get_settings(request)
    if limit is None:
        return settings.default_page_size
    if limit < 1:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "limit must be positive")
    return min(limit, settings.max_page_size)


FactoryDep = Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ConfigDep = Annotated[AppConfig, Depends(get_config)]
FilterDep = Annotated[LeadFilter, Depends(lead_filters)]
LimitDep = Annotated[int, Depends(page_size)]
