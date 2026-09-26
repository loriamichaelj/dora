"""scripts/deploy/smoke_test.py against a fake Dora front door (cloud design §7.2)."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import smoke_test as st

SHA = "a" * 40
SPA = '<!doctype html><html><body><div id="root"></div></body></html>'


@dataclass
class FakeSite:
    """nginx in front of the api, as §6.4 wires it: routes and a warm-up delay."""

    not_ready_for: int = 0  # /readyz answers 503 this many times first
    git_sha: str = SHA
    metrics_exposed: bool = False
    readyz_calls: int = 0
    routes: dict[str, tuple[int, str, str]] = field(default_factory=dict)
    url: str = ""

    def respond(self, path: str) -> tuple[int, str, str]:
        if path in self.routes:
            return self.routes[path]
        if path == "/readyz":
            self.readyz_calls += 1
            ok = self.readyz_calls > self.not_ready_for
            return (200 if ok else 503), "application/json", json.dumps({"status": "ok"})
        if path == "/healthz":
            return 200, "application/json", '{"status": "ok"}'
        if path == "/version":
            return 200, "application/json", json.dumps({"git_sha": self.git_sha})
        if path.startswith("/api/v1/services"):
            return 200, "application/json", json.dumps({"items": [], "total": 0})
        if path == "/metrics" and self.metrics_exposed:
            return (
                200,
                "text/plain",
                "# HELP http_requests_total x\n# TYPE http_requests_total counter\n",
            )
        return 200, "text/html", SPA  # SPA fallback, including /metrics


@pytest.fixture
def site() -> Iterator[FakeSite]:
    fake = FakeSite()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

        def do_GET(self) -> None:
            status, ctype, body = fake.respond(self.path)
            data = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    fake.url = f"http://127.0.0.1:{server.server_address[1]}"
    yield fake
    server.shutdown()


def run(site: FakeSite, git_sha: str | None = SHA, attempts: int = 3) -> list[str]:
    return st.smoke(site.url, git_sha, ready_attempts=attempts, ready_delay_s=0)


def test_a_healthy_deploy_passes_every_check(
    site: FakeSite, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(site) == []
    out = capsys.readouterr().out
    assert out.count("  ok    ") == 7
    assert "/deployments serves the SPA" in out


def test_readyz_is_retried_while_tasks_warm_up(site: FakeSite) -> None:
    site.not_ready_for = 2
    assert run(site) == []
    assert site.readyz_calls == 3


def test_readyz_that_never_answers_fails(site: FakeSite) -> None:
    site.not_ready_for = 99
    [failure] = run(site, attempts=3)
    assert "/readyz never answered 200 in 3 attempts (last: 503)" in failure


def test_the_wrong_commit_fails(site: FakeSite) -> None:
    site.git_sha = "b" * 40
    [failure] = run(site)
    assert f"expected {SHA}" in failure


def test_exposed_metrics_fail(site: FakeSite) -> None:
    site.metrics_exposed = True
    [failure] = run(site)
    assert "/metrics not exposed" in failure


def test_every_failure_is_reported_not_just_the_first(site: FakeSite) -> None:
    site.routes["/healthz"] = (502, "text/html", "bad gateway")
    site.routes["/api/v1/services?limit=1"] = (500, "application/json", "{}")
    site.routes["/deployments"] = (404, "text/html", "not found")
    failures = run(site)
    assert len(failures) == 3


def test_an_unreachable_site_fails_cleanly() -> None:
    failures = st.smoke("http://127.0.0.1:9", SHA, ready_attempts=1, ready_delay_s=0)
    assert len(failures) == 7  # every check fails; nothing raises


def test_cli_exit_codes(site: FakeSite, capsys: pytest.CaptureFixture[str]) -> None:
    assert st.main(["--base-url", site.url, "--git-sha", SHA, "--ready-delay", "0"]) == 0
    site.git_sha = "b" * 40
    assert st.main(["--base-url", site.url, "--git-sha", SHA, "--ready-delay", "0"]) == 1
    assert "::error::1 smoke check(s) failed" in capsys.readouterr().out
    with pytest.raises(SystemExit) as exc:
        st.main(["--base-url", "ftp://example.com"])
    assert exc.value.code == 2
