#!/usr/bin/env python3
"""Smoke-test a running Dora through its front door (docs/CLOUD-DEVOPS-DESIGN.md §7.2 step 10).

    python3 scripts/deploy/smoke_test.py --base-url http://<alb-dns-name> --git-sha <sha>

Checks, in order: /readyz answers 200 (retrying while tasks warm up); /healthz
answers; /version reports the expected commit; an API list call works; the SPA
and a client-side route are served; /metrics does not expose Prometheus
output. Every check runs and is reported, so one failure doesn't hide another.
The same script runs against the local E2E stack in `make e2e`.

Standard library only, Python 3.10+ (D58). Exit codes: 0 all checks passed,
1 a check failed, 2 bad usage.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
TIMEOUT_S = 5.0
SPA_MARKER = '<div id="root">'


@dataclass
class Response:
    status: int
    content_type: str
    body: str


def fetch(url: str) -> Response:
    """GET a URL; HTTP error statuses come back as responses, not exceptions."""
    request = urllib.request.Request(url, headers={"User-Agent": "dora-smoke-test"})  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as resp:  # noqa: S310
            return Response(resp.status, resp.headers.get("Content-Type", ""), resp.read().decode())
    except urllib.error.HTTPError as exc:
        return Response(exc.code, exc.headers.get("Content-Type", ""), exc.read().decode())


class Smoke:
    def __init__(self, base_url: str, fetcher: Callable[[str], Response] = fetch) -> None:
        self.base = base_url.rstrip("/")
        self.fetcher = fetcher
        self.failures: list[str] = []

    def get(self, path: str) -> Response | None:
        try:
            return self.fetcher(self.base + path)
        except (urllib.error.URLError, OSError) as exc:
            self.fail(f"GET {path}: {exc}")
            return None

    def ok(self, message: str) -> None:
        print(f"  ok    {message}", flush=True)

    def fail(self, message: str) -> None:
        self.failures.append(message)
        print(f"  FAIL  {message}", flush=True)

    def check(self, condition: bool, message: str) -> None:
        (self.ok if condition else self.fail)(message)

    # ---- the checks ----

    def readyz(self, attempts: int, delay_s: float) -> None:
        for attempt in range(1, attempts + 1):
            try:
                resp = self.fetcher(self.base + "/readyz")
                if resp.status == 200:
                    self.ok(f"/readyz 200 (attempt {attempt})")
                    return
                detail = f"{resp.status}"
            except (urllib.error.URLError, OSError) as exc:
                detail = str(exc)
            if attempt < attempts:
                time.sleep(delay_s)
        self.fail(f"/readyz never answered 200 in {attempts} attempts (last: {detail})")

    def healthz(self) -> None:
        resp = self.get("/healthz")
        if resp:
            self.check(resp.status == 200, f"/healthz {resp.status}")

    def version(self, git_sha: str | None) -> None:
        resp = self.get("/version")
        if not resp:
            return
        if resp.status != 200:
            self.fail(f"/version {resp.status}")
            return
        reported = json.loads(resp.body).get("git_sha")
        if git_sha:
            self.check(reported == git_sha, f"/version git_sha {reported} (expected {git_sha})")
        else:
            self.ok(f"/version git_sha {reported}")

    def api_list(self) -> None:
        resp = self.get("/api/v1/services?limit=1")
        if not resp:
            return
        items = json.loads(resp.body).get("items") if resp.status == 200 else None
        self.check(
            resp.status == 200 and isinstance(items, list),
            f"/api/v1/services {resp.status}",
        )

    def spa(self, path: str) -> None:
        resp = self.get(path)
        if resp:
            self.check(
                resp.status == 200 and "text/html" in resp.content_type and SPA_MARKER in resp.body,
                f"{path} serves the SPA ({resp.status}, {resp.content_type or 'no type'})",
            )

    def metrics_hidden(self) -> None:
        resp = self.get("/metrics")
        if resp:
            exposed = "# TYPE " in resp.body or "# HELP " in resp.body
            self.check(not exposed, f"/metrics not exposed ({resp.status})")


def smoke(
    base_url: str,
    git_sha: str | None,
    *,
    ready_attempts: int = 30,
    ready_delay_s: float = 5.0,
    fetcher: Callable[[str], Response] = fetch,
) -> list[str]:
    """Run every check; return the failures."""
    print(f"smoke test: {base_url}", flush=True)
    s = Smoke(base_url, fetcher)
    s.readyz(ready_attempts, ready_delay_s)
    s.healthz()
    s.version(git_sha)
    s.api_list()
    s.spa("/")
    s.spa("/deployments")  # a client-side route: nginx falls back to index.html
    s.metrics_hidden()
    return s.failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--git-sha", help="commit /version must report")
    parser.add_argument("--ready-attempts", type=int, default=30)
    parser.add_argument("--ready-delay", type=float, default=5.0, help="seconds between attempts")
    args = parser.parse_args(argv)
    if urllib.parse.urlparse(args.base_url).scheme not in ("http", "https"):
        parser.error("--base-url must be an http(s) URL")
    failures = smoke(
        args.base_url,
        args.git_sha,
        ready_attempts=args.ready_attempts,
        ready_delay_s=args.ready_delay,
    )
    if failures:
        print(f"::error::{len(failures)} smoke check(s) failed: {'; '.join(failures)}")
        return EXIT_FAILED
    print("smoke test passed", flush=True)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
