"""The constraint-violation backstop (§6.3) and If-Match parsing."""

import json

import pytest
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request

from app.concurrency import check_if_match
from app.problems import PreconditionFailed, PreconditionRequired, handle_integrity


class FakeAsyncpgError(Exception):
    def __init__(self, constraint_name: str) -> None:
        self.constraint_name = constraint_name


class FakeDbapiError(Exception):
    def __init__(self, sqlstate: str, constraint: str) -> None:
        self.sqlstate = sqlstate
        self.__cause__ = FakeAsyncpgError(constraint)


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/api/v1/things", "headers": []})


@pytest.mark.parametrize(
    ("sqlstate", "status"),
    [("23505", 409), ("23503", 409), ("23514", 422), ("23502", 422)],
)
async def test_integrity_errors_map_to_problems(sqlstate: str, status: int) -> None:
    exc = IntegrityError("INSERT ...", {}, FakeDbapiError(sqlstate, "uq_services_slug"))
    resp = await handle_integrity(_request(), exc)
    assert resp.status_code == status
    assert resp.media_type == "application/problem+json"
    body = json.loads(bytes(resp.body))
    assert "uq_services_slug" in body["detail"]
    assert "INSERT" not in body["detail"]  # never leak SQL
    assert body["instance"] == "/api/v1/things"


@pytest.mark.parametrize("header", ['"3"', '"1", "3"', "*", ' "3" '])
def test_if_match_accepts(header: str) -> None:
    check_if_match(header, 3)


@pytest.mark.parametrize("header", ['"2"', 'W/"3"', "3", '"3'])
def test_if_match_rejects(header: str) -> None:
    with pytest.raises(PreconditionFailed):
        check_if_match(header, 3)


@pytest.mark.parametrize("header", [None, "", "   "])
def test_if_match_missing(header: str | None) -> None:
    with pytest.raises(PreconditionRequired):
        check_if_match(header, 3)


def test_ingest_race_classifier() -> None:
    from app.problems import Conflict, field_error
    from app.services.ingest import _is_external_id_race

    raced = Conflict("dup", errors=[field_error("external_id", "taken", type_="unique")])
    assert _is_external_id_race(raced)
    assert not _is_external_id_race(Conflict("other conflict"))
    unique = IntegrityError("INSERT", {}, FakeDbapiError("23505", "uq_service_external"))
    assert _is_external_id_race(unique)
    other = IntegrityError("INSERT", {}, FakeDbapiError("23505", "uq_service_sha"))
    assert not _is_external_id_race(other)


def test_route_template_rebuilds_the_router_prefix() -> None:
    import re

    from app.observability import UNMATCHED_ROUTE, route_template

    class FakeRoute:
        path_format = "/services/{service_id}"
        path_regex = re.compile(r"^/services/(?P<service_id>[^/]+)$")

    nested = {"route": FakeRoute(), "path": "/api/v1/services/0192"}
    assert route_template(nested) == "/api/v1/services/{service_id}"
    top_level = {"route": FakeRoute(), "path": "/services/0192"}
    assert route_template(top_level) == "/services/{service_id}"
    assert route_template({"path": "/nope"}) == UNMATCHED_ROUTE
