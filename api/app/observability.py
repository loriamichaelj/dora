"""Request context, access logging, and Prometheus metrics (§7.1, §7.2, §13).

`RequestContextMiddleware` is the outermost application middleware. For every
HTTP request it:
- takes a safe inbound `X-Request-ID` or generates a UUIDv4, binds it (and the
  AWS load balancer's `X-Amzn-Trace-Id`, when present) to every log line, and
  echoes it on the response;
- records request count and latency labeled by *route template*, never the raw
  path, so metrics cardinality stays bounded;
- writes one access log line per request (DEBUG for operational endpoints);
- turns an unhandled exception into a problem+json 500 that still carries the
  request ID, so a user can quote it.
"""

import json
import logging
import re
import time
import uuid
from collections.abc import Iterable

import structlog
from prometheus_client import CollectorRegistry, Counter, Histogram
from prometheus_client.core import GaugeMetricFamily, Metric
from prometheus_client.registry import Collector
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.pool import QueuePool
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.problems import PROBLEM_JSON

log = structlog.get_logger("app.access")

REQUEST_ID_HEADER = "X-Request-ID"
TRACE_ID_HEADER = "X-Amzn-Trace-Id"
OPERATIONAL_PATHS = frozenset({"/healthz", "/readyz", "/metrics", "/version"})
UNMATCHED_ROUTE = "unmatched"

# Accept a caller's request ID only if it's short and harmless in logs/headers.
_SAFE_ID = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")


def route_template(scope: Scope) -> str:
    """The matched route's full template, e.g. /api/v1/services/{service_id}.

    FastAPI nests included routers, so `scope["route"].path_format` holds only
    the innermost part (/services/{service_id}). The router prefix is the part
    of the request path in front of where the route's own pattern matches;
    this app's prefixes are literal (/api/v1), so no raw values can leak into
    the label."""
    route = scope.get("route")
    template = getattr(route, "path_format", None)
    pattern = getattr(route, "path_regex", None)
    if not template or pattern is None:
        return UNMATCHED_ROUTE
    path: str = scope["path"]
    if pattern.match(path):
        return str(template)
    for index, char in enumerate(path):
        if char == "/" and index and pattern.match(path[index:]):
            return path[:index] + str(template)
    return str(template)


def pick_request_id(inbound: str | None) -> str:
    if inbound and _SAFE_ID.match(inbound):
        return inbound
    return str(uuid.uuid4())


class HttpMetrics:
    """Per-app registry, so test apps never collide on global registration."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry(auto_describe=True)
        self.requests = Counter(
            "http_requests_total",
            "HTTP requests by route template, method, and status code.",
            ["method", "route", "status"],
            registry=self.registry,
        )
        self.latency = Histogram(
            "http_request_duration_seconds",
            "HTTP request latency by route template and method.",
            ["method", "route"],
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
            registry=self.registry,
        )

    def watch_pool(self, engine: AsyncEngine) -> None:
        self.registry.register(PoolCollector(engine))


class PoolCollector(Collector):
    """DB connection pool gauges, read at scrape time."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    def collect(self) -> Iterable[Metric]:
        pool = self.engine.sync_engine.pool
        if not isinstance(pool, QueuePool):
            return
        for name, doc, value in (
            ("db_pool_size", "Configured pool size.", pool.size()),
            ("db_pool_checked_out", "Connections currently in use.", pool.checkedout()),
            ("db_pool_checked_in", "Idle connections in the pool.", pool.checkedin()),
            ("db_pool_overflow", "Connections open beyond pool_size.", max(pool.overflow(), 0)),
        ):
            yield GaugeMetricFamily(name, doc, value=value)


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, metrics: HttpMetrics) -> None:
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        request_id = pick_request_id(headers.get(REQUEST_ID_HEADER.lower()))
        trace_id = headers.get(TRACE_ID_HEADER.lower())
        method = scope["method"]
        path = scope["path"]
        status = 500
        response_started = False
        started = time.perf_counter()

        async def send_with_id(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id, trace_id=trace_id)
        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            log.exception("unhandled_exception", method=method, path=path)
            if response_started:
                raise
            await self._send_500(send, request_id, path)
            status = 500
        finally:
            duration = time.perf_counter() - started
            route = route_template(scope)
            self.metrics.requests.labels(method, route, str(status)).inc()
            self.metrics.latency.labels(method, route).observe(duration)
            log.log(
                logging.DEBUG if path in OPERATIONAL_PATHS else logging.INFO,
                "request",
                method=method,
                route=route,
                status=status,
                duration_ms=round(duration * 1000, 2),
            )
            structlog.contextvars.clear_contextvars()

    @staticmethod
    async def _send_500(send: Send, request_id: str, path: str) -> None:
        body = json.dumps(
            {
                "type": "about:blank",
                "title": "Internal Server Error",
                "status": 500,
                "detail": "An unexpected error occurred.",
                "instance": path,
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 500,
                "headers": [
                    (b"content-type", PROBLEM_JSON.encode()),
                    (b"content-length", str(len(body)).encode()),
                    (REQUEST_ID_HEADER.encode(), request_id.encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
