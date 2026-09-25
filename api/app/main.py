"""App factory: middleware, routers, and exception handlers."""

from fastapi import FastAPI

from app.config import get_settings
from app.routers import health


def create_app() -> FastAPI:
    settings = get_settings()
    docs = settings.enable_api_docs
    app = FastAPI(
        title="DORA Deployment Tracker",
        version=settings.app_version,
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.include_router(health.router)
    return app


app = create_app()
