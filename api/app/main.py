"""App factory: middleware, routers, and exception handlers."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from app.config import DatabaseSettings, Settings, get_database_settings, get_settings
from app.db import create_engine, create_sessionmaker
from app.logging import configure_logging
from app.observability import HttpMetrics, RequestContextMiddleware
from app.problems import install_problem_handlers
from app.routers import deployments, failures, health, ingest, metrics, services

API_PREFIX = "/api/v1"


def create_app(
    settings: Settings | None = None, db_settings: DatabaseSettings | None = None
) -> FastAPI:
    settings = settings or get_settings()
    db_settings = db_settings or get_database_settings()
    configure_logging(settings.log_level)
    http_metrics = HttpMetrics()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # The engine connects lazily, so startup never blocks on the database.
        engine = create_engine(db_settings)
        app.state.engine = engine
        app.state.sessionmaker = create_sessionmaker(engine)
        http_metrics.watch_pool(engine)
        try:
            yield
        finally:
            await engine.dispose()

    docs = settings.enable_api_docs
    app = FastAPI(
        title="DORA Deployment Tracker",
        version=settings.app_version,
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.metrics = http_metrics
    install_problem_handlers(app)
    app.add_middleware(RequestContextMiddleware, metrics=http_metrics)

    api = APIRouter(prefix=API_PREFIX)
    api.include_router(services.router)
    api.include_router(deployments.router)
    api.include_router(failures.router)
    api.include_router(ingest.router)
    api.include_router(metrics.router)

    app.include_router(health.router)
    app.include_router(api)
    return app


app = create_app()
