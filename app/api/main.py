import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import __version__
from app.api.middleware import RequestContextMiddleware
from app.api.routes import router
from app.config import load_config
from app.config.models import AppConfig
from app.db.session import create_engine, create_session_factory
from app.settings import Settings, get_settings
from app.telemetry import configure_logging

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    config: AppConfig | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> FastAPI:
    resolved = settings or get_settings()
    configure_logging(resolved.log_level, resolved.log_format)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        engine = None
        if session_factory is None:
            engine = create_engine(resolved.database_url)
            app.state.session_factory = create_session_factory(engine)
        try:
            yield
        finally:
            if engine is not None:
                await engine.dispose()

    app = FastAPI(
        title="LeadPipe",
        version=__version__,
        summary="Collect, normalize, validate and deduplicate business leads.",
        lifespan=lifespan,
    )
    app.state.settings = resolved
    app.state.config = config or load_config(Path(resolved.config_path))
    if session_factory is not None:
        app.state.session_factory = session_factory

    if resolved.allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=resolved.allowed_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["X-API-Key", "Content-Type"],
        )

    app.add_middleware(RequestContextMiddleware)
    app.include_router(router)
    return app
