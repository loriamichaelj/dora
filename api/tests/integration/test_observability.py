"""Request IDs, JSON logs, Prometheus metrics, readiness, and DB TLS (§7.1, §7.2, §13)."""

import asyncio
import io
import json
import logging
import os
import re
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

import pytest
import structlog
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from testcontainers.community.postgres import PostgresContainer

from app.config import DatabaseSettings
from app.db import create_engine
from app.main import create_app
from tests.integration.conftest import POSTGRES_IMAGE, Database, database_for, start_postgres
from tests.integration.helpers import create_service

KEY = os.environ["INGEST_API_KEY"]
INGEST = "/api/v1/events/deployments"


LogReader = Callable[[], list[dict[str, Any]]]


@pytest.fixture
def read_logs() -> Iterator[LogReader]:
    """Redirect the real JSON log handler into a buffer; the returned callable
    parses everything written so far, one dict per line."""
    handler = next(
        h
        for h in logging.getLogger().handlers
        if isinstance(h, logging.StreamHandler)
        and isinstance(h.formatter, structlog.stdlib.ProcessorFormatter)
    )
    buffer = io.StringIO()
    original = handler.setStream(buffer)

    def read() -> list[dict[str, Any]]:
        return [json.loads(line) for line in buffer.getvalue().splitlines() if line]

    try:
        yield read
    finally:
        handler.setStream(original)  # type: ignore[arg-type]


# ---- request IDs ----


async def test_request_id_is_generated_echoed_or_replaced(api: AsyncClient) -> None:
    generated = (await api.get("/healthz")).headers["x-request-id"]
    assert uuid.UUID(generated).version == 4

    inbound = "abc-123.def:456"
    echoed = await api.get("/healthz", headers={"X-Request-ID": inbound})
    assert echoed.headers["x-request-id"] == inbound

    for unsafe in ("has spaces", "x" * 129, "semi;colon"):
        replaced = await api.get("/healthz", headers={"X-Request-ID": unsafe})
        assert uuid.UUID(replaced.headers["x-request-id"]).version == 4


async def test_problem_responses_carry_the_request_id(api: AsyncClient) -> None:
    resp = await api.get(f"/api/v1/services/{uuid.uuid4()}", headers={"X-Request-ID": "req-404"})
    assert resp.status_code == 404
    assert resp.headers["x-request-id"] == "req-404"


# ---- JSON access logs ----


async def test_access_log_is_json_with_request_context(
    api: AsyncClient, read_logs: LogReader
) -> None:
    service = await create_service(api)
    await api.get(
        f"/api/v1/services/{service['id']}",
        headers={
            "X-Request-ID": "req-42",
            "X-Amzn-Trace-Id": "Root=1-67891233-abcdef012345678912345678",
        },
    )
    await api.get("/healthz")
    access = [line for line in read_logs() if line["event"] == "request"]
    get_line = next(line for line in access if line.get("request_id") == "req-42")
    assert get_line["trace_id"] == "Root=1-67891233-abcdef012345678912345678"
    assert get_line["route"] == "/api/v1/services/{service_id}"  # template, not the raw path
    assert (get_line["method"], get_line["status"], get_line["level"]) == ("GET", 200, "info")
    assert get_line["logger"] == "app.access"
    assert isinstance(get_line["duration_ms"], float)
    assert re.match(r"^\d{4}-\d\d-\d\dT.*Z$", get_line["timestamp"])
    # Operational endpoints log at DEBUG, below the INFO threshold.
    assert not any(line["route"] == "/healthz" for line in access)


async def test_secrets_never_reach_the_log(api: AsyncClient, read_logs: LogReader) -> None:
    await create_service(api)
    event = {
        "service_slug": "checkout-api",
        "external_id": "gha-1-1-production",
        "environment": "production",
        "release": "v1",
        "status": "in_progress",
        "started_at": "2026-09-20T10:00:00Z",
    }
    assert (await api.post(INGEST, headers={"X-API-Key": KEY}, json=event)).status_code == 201
    assert (
        await api.post(INGEST, headers={"X-API-Key": "wrong" * 10}, json=event)
    ).status_code == 401
    # Even a careless log call with secret-looking fields is redacted.
    structlog.get_logger("probe").info("probe", db_password="hunter2", api_key=KEY)

    lines = read_logs()
    assert any(line["event"] == "probe" for line in lines)
    raw = json.dumps(lines)
    assert KEY not in raw
    assert "hunter2" not in raw
    assert "wrong" * 10 not in raw


def test_redaction_processor() -> None:
    from app.logging import REDACTED, redact_secrets

    event = redact_secrets(
        None,
        "info",
        {"event": "x", "db_password": "p", "X-API-Key": "k", "authorization": "a", "route": "/r"},
    )
    assert event == {
        "event": "x",
        "db_password": REDACTED,
        "X-API-Key": REDACTED,
        "authorization": REDACTED,
        "route": "/r",
    }


# ---- unhandled errors ----


async def test_unhandled_exception_is_a_problem_500_with_request_id() -> None:
    app = create_app()

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("kaboom: internal detail")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/boom", headers={"X-Request-ID": "req-500"})
    assert resp.status_code == 500
    assert resp.headers["content-type"] == "application/problem+json"
    assert resp.headers["x-request-id"] == "req-500"
    assert "kaboom" not in resp.text


# ---- Prometheus ----


async def test_metrics_use_route_templates_and_expose_pool_gauges(api: AsyncClient) -> None:
    service = await create_service(api)
    await api.get(f"/api/v1/services/{service['id']}")
    await api.get("/api/v1/nope")
    body = (await api.get("/metrics")).text
    assert 'route="/api/v1/services/{service_id}"' in body
    assert 'route="unmatched"' in body
    assert service["id"] not in body  # no raw paths, bounded cardinality
    assert "http_request_duration_seconds_bucket" in body
    for gauge in ("db_pool_size", "db_pool_checked_out", "db_pool_checked_in", "db_pool_overflow"):
        assert re.search(rf"^{gauge} \d+\.\d+$", body, re.M), gauge


# ---- readiness ----


async def test_readyz_ok(api: AsyncClient) -> None:
    resp = await api.get("/readyz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready", "checks": {"database": "ok"}}


@pytest.fixture
async def unreachable_api(migrated: Database) -> AsyncIterator[AsyncClient]:
    """An API whose database port has nothing listening: connection refused."""
    settings = migrated.app.model_copy(update={"db_port": 1})
    app = create_app(db_settings=settings)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def test_unreachable_database_is_503_but_alive(unreachable_api: AsyncClient) -> None:
    ready = await unreachable_api.get("/readyz")
    assert ready.status_code == 503
    assert ready.json() == {"status": "not_ready", "checks": {"database": "error"}}
    assert (await unreachable_api.get("/healthz")).status_code == 200

    data = await unreachable_api.get("/api/v1/services")
    assert data.status_code == 503
    assert data.json()["type"] == "urn:dora:problem:database-unavailable"
    assert data.headers["retry-after"] == "5"
    assert data.headers["x-request-id"]


@pytest.fixture
def paused_database() -> Iterator[Database]:
    container = start_postgres()
    try:
        yield database_for(container)
    finally:
        wrapped = container.get_wrapped_container()
        wrapped.reload()
        if wrapped.attrs["State"]["Paused"]:
            wrapped.unpause()
        container.stop()


async def test_frozen_database_times_out_readiness_and_recovers(paused_database: Database) -> None:
    """A hung database (paused container) must make /readyz answer 503 within
    its 2s budget, keep /healthz green, and recover without an API restart."""
    settings = DatabaseSettings(
        db_host=paused_database.host,
        db_port=paused_database.port,
        db_name="dora",
        db_user="postgres",
        db_password="postgres",
    )
    app = create_app(db_settings=settings)
    transport = ASGITransport(app=app)
    database = paused_database.container.get_wrapped_container()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        assert (await client.get("/readyz")).status_code == 200

        database.pause()
        for _ in range(2):  # the second check reuses the in-flight probe
            started = time.monotonic()
            frozen = await client.get("/readyz")
            assert time.monotonic() - started < 3.0
            assert frozen.status_code == 503
            assert frozen.json()["checks"]["database"] == "timeout"
        assert (await client.get("/healthz")).status_code == 200

        database.unpause()
        deadline = time.monotonic() + 30
        while (await client.get("/readyz")).status_code != 200:
            assert time.monotonic() < deadline, "readiness never recovered"
            await asyncio.sleep(0.5)


# ---- DB TLS (DB_SSL_MODE) ----


@pytest.fixture(scope="module")
def tls_postgres() -> Iterator[PostgresContainer]:
    container = PostgresContainer(
        POSTGRES_IMAGE, username="postgres", password="postgres", dbname="dora", driver=None
    ).with_command(
        "-c ssl=on "
        "-c ssl_cert_file=/etc/ssl/certs/ssl-cert-snakeoil.pem "
        "-c ssl_key_file=/etc/ssl/private/ssl-cert-snakeoil.key"
    )
    container.start()
    try:
        yield container
    finally:
        container.stop()


def _tls_settings(container: PostgresContainer, mode: str, cafile: str = "") -> DatabaseSettings:
    return DatabaseSettings(
        db_host=container.get_container_host_ip(),
        db_port=int(container.get_exposed_port(5432)),
        db_name="dora",
        db_user="postgres",
        db_password="postgres",
        db_ssl_mode=mode,  # type: ignore[arg-type]
        db_ssl_root_cert=cafile,
    )


async def _connection_is_encrypted(settings: DatabaseSettings) -> bool:
    engine = create_engine(settings, null_pool=True)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()")
            )
            return bool(result.scalar_one())
    finally:
        await engine.dispose()


async def test_ssl_mode_require_encrypts(tls_postgres: PostgresContainer) -> None:
    assert await _connection_is_encrypted(_tls_settings(tls_postgres, "require"))
    assert not await _connection_is_encrypted(_tls_settings(tls_postgres, "disable"))


async def test_ssl_mode_verify_full_rejects_an_untrusted_certificate(
    tls_postgres: PostgresContainer,
) -> None:
    # The snakeoil certificate isn't signed by any CA the client trusts.
    with pytest.raises(Exception, match=r"(?i)certificate verify failed"):
        await _connection_is_encrypted(_tls_settings(tls_postgres, "verify-full"))
