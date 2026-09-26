"""Fixtures for record_deploy.py: throwaway git repos and a fake tracker API.

The fake implements only what the script calls, with the real API's shapes
and ingest semantics (upsert on external_id: 201 new, 200 existing).
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import urllib.parse
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

API_KEY = "test-key-0123456789abcdef0123456789abcd"


@dataclass
class FakeTracker:
    services: list[dict[str, Any]] = field(default_factory=list)
    deployments: list[dict[str, Any]] = field(default_factory=list)
    version: dict[str, str] = field(
        default_factory=lambda: {
            "version": "0.1.0",
            "git_sha": "unset",
            "build_time": "2026-09-25T12:00:00Z",
        }
    )
    ready: bool = True
    requests: list[tuple[str, str]] = field(default_factory=list)
    url: str = ""

    def deployments_for(self, slug: str) -> list[dict[str, Any]]:
        ids = {s["id"] for s in self.services if s["slug"] == slug}
        return [d for d in self.deployments if d["service_id"] in ids]


def _handler(tracker: FakeTracker) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:  # keep test output quiet
            pass

        def _send(self, status: int, body: object) -> None:
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length)) if length else {}

        def do_GET(self) -> None:
            url = urllib.parse.urlsplit(self.path)
            query = dict(urllib.parse.parse_qsl(url.query))
            tracker.requests.append(("GET", url.path))
            if url.path == "/version":
                return self._send(200, tracker.version)
            if url.path == "/readyz":
                return self._send(200 if tracker.ready else 503, {"status": "x"})
            if url.path == "/api/v1/services":
                q = query.get("q", "")
                items = [s for s in tracker.services if q in s["slug"]]
                return self._send(200, {"items": items, "total": len(items)})
            if url.path == "/api/v1/deployments":
                items = [
                    d
                    for d in tracker.deployments
                    if d["service_id"] == query.get("service_id")
                    and d["environment"] == query.get("environment")
                    and d["status"] == query.get("status", d["status"])
                ]
                items.sort(key=lambda d: d.get("finished_at") or "", reverse=True)
                limit = int(query.get("limit", 50))
                return self._send(200, {"items": items[:limit], "total": len(items)})
            return self._send(404, {"detail": "no route"})

        def do_POST(self) -> None:
            path = urllib.parse.urlsplit(self.path).path
            tracker.requests.append(("POST", path))
            body = self._body()
            if path == "/api/v1/services":
                service = {"id": f"svc-{len(tracker.services) + 1}", **body}
                tracker.services.append(service)
                return self._send(201, service)
            if path == "/api/v1/events/deployments":
                if self.headers.get("X-API-Key") != API_KEY:
                    return self._send(401, {"detail": "bad key"})
                [service] = [s for s in tracker.services if s["slug"] == body["service_slug"]]
                existing = next(
                    (
                        d
                        for d in tracker.deployments
                        if d["service_id"] == service["id"]
                        and d["external_id"] == body["external_id"]
                    ),
                    None,
                )
                fields = {k: v for k, v in body.items() if k != "service_slug"}
                if existing is None:
                    deployment = {"id": f"dep-{len(tracker.deployments) + 1}", **fields}
                    deployment["service_id"] = service["id"]
                    tracker.deployments.append(deployment)
                    return self._send(201, deployment)
                existing.update(fields)
                return self._send(200, existing)
            return self._send(404, {"detail": "no route"})

    return Handler


@pytest.fixture
def tracker() -> Iterator[FakeTracker]:
    fake = FakeTracker()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(fake))
    fake.url = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield fake
    server.shutdown()


class Repo:
    def __init__(self, path: Path) -> None:
        self.path = path

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.path, check=True, capture_output=True, text=True
        ).stdout.strip()

    def commit(self, message: str) -> str:
        (self.path / "log.txt").open("a").write(message + "\n")
        self.git("add", "log.txt")
        self.git("commit", "-q", "-m", message)
        return self.head()

    def head(self) -> str:
        return self.git("rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Repo:
    path = tmp_path / "repo"
    path.mkdir()
    r = Repo(path)
    r.git("init", "-q", "-b", "dev")
    r.git("config", "user.email", "dev@example.com")
    r.git("config", "user.name", "Dev")
    r.git("config", "commit.gpgsign", "false")
    r.commit("initial commit")
    monkeypatch.chdir(path)  # no .env here; the script must not read the real one
    for var in ("INGEST_API_KEY", "DORA_API_URL", "DORA_SELF_SERVICE", "DEPLOY_STARTED_AT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("APP_VERSION", raising=False)
    return r
