"""Structured JSON logging to stdout (§13).

One event per line with `timestamp`, `level`, `logger`, `event`, and, inside a
request, `request_id` and `trace_id` (bound by the request middleware through
contextvars). Standard-library loggers (uvicorn, sqlalchemy) are routed through
the same renderer, so every line on stdout is JSON.

Request bodies are never logged. As a backstop, any field whose name looks like
a secret is redacted before rendering.
"""

import logging
import sys

import structlog
from structlog.types import EventDict, Processor, WrappedLogger

REDACTED = "[redacted]"
_SECRET_MARKERS = ("password", "secret", "api_key", "apikey", "x-api-key", "authorization", "token")


def redact_secrets(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    for key in list(event_dict):
        if any(marker in key.lower() for marker in _SECRET_MARKERS):
            event_dict[key] = REDACTED
    return event_dict


def _shared_processors() -> list[Processor]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
        redact_secrets,
    ]


def configure_logging(level: str = "INFO") -> None:
    """Idempotent: safe to call from the app factory on every startup."""
    shared = _shared_processors()
    structlog.configure(
        processors=[
            *shared,
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        # Not cached: structlog.testing.capture_logs must be able to intercept.
        cache_logger_on_first_use=False,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # Uvicorn's own handlers would print plain text; send everything to root.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
    # SQL echo would log bound parameters; keep the engine quiet.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
