"""Shared test configuration.

Tests never read a .env file: every setting the app needs is supplied here.
"""

import os
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["INGEST_API_KEY"] = "test-ingest-key-0123456789abcdef0123"
os.environ["APP_VERSION"] = "0.0.0-test"
os.environ["GIT_SHA"] = "0" * 40
os.environ["BUILD_TIME"] = "2026-01-01T00:00:00Z"

from app.main import create_app  # settings must see the env above


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
