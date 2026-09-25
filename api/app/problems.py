"""RFC 9457 problem details (§7.1).

Every error the API returns is `application/problem+json` with `type`, `title`,
`status`, `detail`, `instance`, and, for field-level validation, `errors[]`.
Domain code raises `Problem` subclasses; the handlers below also translate
FastAPI's validation errors, unknown routes, and database constraint
violations (the §6.3 backstop) into the same shape.
"""

from http import HTTPStatus
from typing import Any, ClassVar

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_JSON = "application/problem+json"
TYPE_PREFIX = "urn:dora:problem:"

log = structlog.get_logger(__name__)


class FieldError(BaseModel):
    location: str
    field: str
    message: str
    type: str


class ProblemDetail(BaseModel):
    type: str
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    errors: list[FieldError] | None = None


class Problem(Exception):
    status: HTTPStatus = HTTPStatus.INTERNAL_SERVER_ERROR
    slug: str | None = None
    headers: ClassVar[dict[str, str] | None] = None

    def __init__(
        self,
        detail: str | None = None,
        *,
        errors: list[FieldError] | None = None,
        slug: str | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.errors = errors
        if slug is not None:
            self.slug = slug

    @property
    def type_uri(self) -> str:
        return f"{TYPE_PREFIX}{self.slug}" if self.slug else "about:blank"

    @property
    def title(self) -> str:
        return self.status.phrase


class NotFound(Problem):
    status = HTTPStatus.NOT_FOUND
    slug = "not-found"


class Conflict(Problem):
    status = HTTPStatus.CONFLICT
    slug = "conflict"


class Unprocessable(Problem):
    status = HTTPStatus.UNPROCESSABLE_ENTITY
    slug = "validation"


class PreconditionFailed(Problem):
    status = HTTPStatus.PRECONDITION_FAILED
    slug = "precondition-failed"


class PreconditionRequired(Problem):
    status = HTTPStatus.PRECONDITION_REQUIRED
    slug = "precondition-required"


class Unauthorized(Problem):
    status = HTTPStatus.UNAUTHORIZED
    slug = "unauthorized"
    # RFC 9110 requires a challenge on 401. The scheme names the header to send.
    headers: ClassVar[dict[str, str] | None] = {
        "WWW-Authenticate": 'ApiKey realm="dora-ingest", header="X-API-Key"'
    }


def field_error(
    field: str, message: str, *, type_: str = "invalid", location: str = "body"
) -> FieldError:
    return FieldError(location=location, field=field, message=message, type=type_)


def problem_response(
    request: Request,
    status: int,
    *,
    type_: str = "about:blank",
    title: str | None = None,
    detail: str | None = None,
    errors: list[FieldError] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ProblemDetail(
        type=type_,
        title=title or HTTPStatus(status).phrase,
        status=status,
        detail=detail,
        instance=request.url.path,
        errors=errors,
    )
    return JSONResponse(
        body.model_dump(exclude_none=True),
        status_code=status,
        media_type=PROBLEM_JSON,
        headers=headers,
    )


def _location_and_field(loc: tuple[Any, ...]) -> tuple[str, str]:
    if not loc:
        return "body", ""
    location = str(loc[0])
    return location, ".".join(str(part) for part in loc[1:])


async def handle_problem(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, Problem)
    return problem_response(
        request,
        exc.status,
        type_=exc.type_uri,
        detail=exc.detail,
        errors=exc.errors,
        headers=exc.headers,
    )


async def handle_validation(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = []
    for err in exc.errors():
        location, field = _location_and_field(tuple(err.get("loc", ())))
        errors.append(
            FieldError(location=location, field=field, message=err["msg"], type=err["type"])
        )
    return problem_response(
        request,
        HTTPStatus.UNPROCESSABLE_ENTITY,
        type_=f"{TYPE_PREFIX}validation",
        detail="The request is invalid. See errors for details.",
        errors=errors,
    )


async def handle_http(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    detail = exc.detail if isinstance(exc.detail, str) else None
    if exc.status_code == HTTPStatus.NOT_FOUND and detail == "Not Found":
        detail = "No such route."
    return problem_response(
        request, exc.status_code, detail=detail, headers=getattr(exc, "headers", None)
    )


# SQLSTATE classes for the constraint backstop (§6.3).
_UNIQUE_VIOLATION = "23505"
_FOREIGN_KEY_VIOLATION = "23503"
_CHECK_VIOLATION = "23514"
_NOT_NULL_VIOLATION = "23502"


async def handle_integrity(request: Request, exc: Exception) -> JSONResponse:
    """Backstop for constraint violations the service layer didn't pre-empt.
    Never leaks raw database messages; names the constraint instead."""
    assert isinstance(exc, IntegrityError)
    orig = exc.orig
    sqlstate = getattr(orig, "sqlstate", None)
    cause = getattr(orig, "__cause__", None)
    constraint = getattr(cause, "constraint_name", None) or "unknown"
    log.warning("constraint_violation", sqlstate=sqlstate, constraint=constraint)

    if sqlstate == _UNIQUE_VIOLATION:
        status, slug, detail = HTTPStatus.CONFLICT, "conflict", "already exists"
    elif sqlstate == _FOREIGN_KEY_VIOLATION:
        status, slug, detail = HTTPStatus.CONFLICT, "conflict", "is still referenced or missing"
    else:
        status, slug, detail = HTTPStatus.UNPROCESSABLE_ENTITY, "validation", "failed a constraint"
    return problem_response(
        request,
        status,
        type_=f"{TYPE_PREFIX}{slug}",
        detail=f"The change violates constraint {constraint!r}: the record {detail}.",
    )


async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled_exception", exc_info=exc)
    return problem_response(
        request,
        HTTPStatus.INTERNAL_SERVER_ERROR,
        detail="An unexpected error occurred.",
    )


def install_problem_handlers(app: FastAPI) -> None:
    app.add_exception_handler(Problem, handle_problem)
    app.add_exception_handler(RequestValidationError, handle_validation)
    app.add_exception_handler(StarletteHTTPException, handle_http)
    app.add_exception_handler(IntegrityError, handle_integrity)
    app.add_exception_handler(Exception, handle_unexpected)


def problem_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI `responses` entries, so the generated client types include the
    problem shape for each status a route can return."""
    return {
        status: {"model": ProblemDetail, "content": {PROBLEM_JSON: {}}}
        for status in (422, *statuses)
    }
