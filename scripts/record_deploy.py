#!/usr/bin/env python3
"""Record a build of the tracker as a deployment of itself (§15).

Posts to the tracker's own public ingest API, like any pipeline would. Runs on
the host (it needs the git repository), uses only the standard library, and
stays compatible with Python 3.10 (D58).

    python3 scripts/record_deploy.py                 # after `make up`
    python3 scripts/record_deploy.py --dry-run       # show the payload only
    python3 scripts/record_deploy.py --status in_progress --external-id gha-1-1-production

Exit codes: 0 success (or any failure with --best-effort), 1 API or network
error, 2 bad usage, 3 refused because the working tree has uncommitted changes.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXIT_OK, EXIT_API, EXIT_USAGE, EXIT_DIRTY = 0, 1, 2, 3
MAX_COMMITS = 500
REQUEST_TIMEOUT_S = 5.0
ATTEMPTS = 3
SERVICE_NAME = "DORA Tracker"
SERVICE_TEAM = "platform"
SEP = "\x1f"


class RecordError(Exception):
    def __init__(self, message: str, exit_code: int = EXIT_API) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def say(message: str) -> None:
    print(f"record_deploy: {message}", flush=True)


def warn(message: str) -> None:
    print(f"record_deploy: warning: {message}", file=sys.stderr, flush=True)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    """ISO 8601 with an offset. Python 3.10's fromisoformat doesn't take `Z`."""
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{value!r} has no UTC offset")
    return parsed


# ---- configuration ----


def read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


class Settings:
    """Environment first, then the repository's .env (§15.2)."""

    def __init__(self, repo: Path) -> None:
        self.dotenv = read_dotenv(Path.cwd() / ".env") or read_dotenv(repo / ".env")

    def get(self, key: str, default: str | None = None) -> str | None:
        return os.environ.get(key) or self.dotenv.get(key) or default


# ---- git ----


@dataclass(frozen=True)
class Commit:
    sha: str
    committed_at: str
    author: str
    message: str

    def payload(self) -> dict[str, Any]:
        body: dict[str, Any] = {"sha": self.sha, "committed_at": self.committed_at}
        if self.author:
            body["author"] = self.author[:200]
        if self.message:
            body["message"] = self.message[:1000]
        return body


class Git:
    def __init__(self, repo: Path) -> None:
        self.repo = repo

    def run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["git", *args], cwd=self.repo, capture_output=True, text=True, check=check
            )
        except subprocess.CalledProcessError as exc:
            raise RecordError(f"git {' '.join(args)} failed: {exc.stderr.strip()}") from exc
        except FileNotFoundError as exc:
            raise RecordError("git is not installed") from exc

    def head(self) -> str:
        return self.run("rev-parse", "HEAD").stdout.strip()

    def is_dirty(self) -> bool:
        return bool(self.run("status", "--porcelain").stdout.strip())

    def has_commit(self, sha: str) -> bool:
        return self.run("cat-file", "-e", f"{sha}^{{commit}}", check=False).returncode == 0

    def is_ancestor(self, older: str, newer: str) -> bool:
        return self.run("merge-base", "--is-ancestor", older, newer, check=False).returncode == 0

    def log(self, *revision_args: str) -> tuple[list[Commit], bool]:
        """Commits newest first, capped at MAX_COMMITS. Returns (commits, truncated)."""
        out = self.run(
            "log",
            f"--format=%H{SEP}%cI{SEP}%ae{SEP}%s",
            f"--max-count={MAX_COMMITS + 1}",
            *revision_args,
        ).stdout
        commits = []
        for line in out.splitlines():
            parts = line.split(SEP)
            if len(parts) == 4:
                commits.append(Commit(*parts))
        return commits[:MAX_COMMITS], len(commits) > MAX_COMMITS


# ---- API ----


class Api:
    def __init__(self, base_url: str, api_key: str) -> None:
        if urllib.parse.urlsplit(base_url).scheme not in ("http", "https"):
            raise RecordError(f"--api-url must be an http(s) URL, not {base_url!r}", EXIT_USAGE)
        self.base = base_url.rstrip("/")
        self.api_key = api_key

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        auth: bool = False,
        ok: tuple[int, ...] = (200,),
    ) -> tuple[int, Any]:
        """Retries network errors and 5xx with exponential backoff (§15.6)."""
        data = None if body is None else json.dumps(body).encode()
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if auth:
            headers["X-API-Key"] = self.api_key
        last_error = ""
        for attempt in range(ATTEMPTS):
            if attempt:
                time.sleep(0.5 * 2 ** (attempt - 1))
            # The scheme is checked to be http(s) in __init__.
            req = urllib.request.Request(  # noqa: S310
                self.base + path, data=data, headers=headers, method=method
            )
            try:
                with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:  # noqa: S310
                    status, raw = resp.status, resp.read()
            except urllib.error.HTTPError as exc:
                status, raw = exc.code, exc.read()
            except (urllib.error.URLError, OSError) as exc:
                last_error = f"{method} {path}: {getattr(exc, 'reason', exc)}"
                continue
            if status >= 500:
                last_error = f"{method} {path}: HTTP {status}"
                continue
            payload = json.loads(raw) if raw else None
            if status not in ok:
                detail = payload.get("detail") if isinstance(payload, dict) else None
                raise RecordError(f"{method} {path}: HTTP {status}: {detail or raw[:200]!r}")
            return status, payload
        raise RecordError(f"the tracker API is unreachable ({last_error})")


# ---- the recording ----


def resolve_service(api: Api, slug: str, ensure: bool, dry_run: bool = False) -> str | None:
    _, page = api.request("GET", "/api/v1/services?" + urllib.parse.urlencode({"q": slug}))
    for item in page["items"]:
        if item["slug"] == slug:
            return str(item["id"])
    if dry_run:
        say(f"service {slug!r} doesn't exist yet (a real run would create it)")
        return None
    if not ensure:
        raise RecordError(f"service {slug!r} doesn't exist; create it or pass --ensure-service")
    _, created = api.request(
        "POST",
        "/api/v1/services",
        {"slug": slug, "name": SERVICE_NAME, "owner_team": SERVICE_TEAM},
        ok=(201,),
    )
    say(f"created service {slug!r}")
    return str(created["id"])


def last_recorded(api: Api, service_id: str, environment: str) -> dict[str, Any] | None:
    query = urllib.parse.urlencode(
        {
            "service_id": service_id,
            "environment": environment,
            "status": "succeeded",
            "sort": "-finished_at",
            "limit": 1,
        }
    )
    _, page = api.request("GET", f"/api/v1/deployments?{query}")
    items = page["items"]
    return items[0] if items else None


def choose_commits(
    git: Git, head: str, last: dict[str, Any] | None
) -> tuple[list[Commit], list[str]]:
    """§15.3's commit range. Returns (commits newest first, notes to print)."""
    if last is None or not last.get("head_sha"):
        # First run (or after `make reset`): only HEAD. The whole history would
        # produce a meaningless lead-time spike.
        commits, _ = git.log("-1", head)
        return commits, ["first recorded build: recording HEAD only"]
    last_sha = str(last["head_sha"])
    if git.has_commit(last_sha) and git.run("rev-parse", last_sha).stdout.strip() == head:
        return [], ["HEAD is unchanged since the last recorded build: recording a rebuild"]
    if git.has_commit(last_sha) and git.is_ancestor(head, last_sha):
        # HEAD is older than what was last recorded: a rollback. It ships no
        # commits that weren't already deployed.
        return [], [f"HEAD is older than the last recorded build ({last_sha[:12]}): a rollback"]
    if git.has_commit(last_sha) and git.is_ancestor(last_sha, head):
        commits, truncated = git.log(f"{last_sha}..{head}")
        notes = [f"recording {len(commits)} commit(s) since {last_sha[:12]}"]
    else:
        since = str(last["finished_at"])
        commits, truncated = git.log(f"--since={since}", head)
        notes = [
            f"history was rewritten ({last_sha[:12]} is not an ancestor of HEAD); "
            f"falling back to commits since {since}"
        ]
    if truncated:
        notes.append(f"range truncated to the newest {MAX_COMMITS} commits")
    return commits, notes


def check_running_build(api: Api, head: str) -> tuple[str, str | None, str | None]:
    """§15.4: (status, release suffix, build_time). Succeeded only when the
    stack is ready and /version reports exactly this commit."""
    build_time = None
    try:
        _, version = api.request("GET", "/version")
        build_time = version.get("build_time")
        running = version.get("git_sha")
    except RecordError:
        return "failed", "unreachable", None
    try:
        api.request("GET", "/readyz")
    except RecordError:
        return "failed", "not-ready", build_time
    if running != head:
        warn(f"/version reports {str(running)[:12]}, but HEAD is {head[:12]}")
        return "failed", "sha-mismatch", build_time
    return "succeeded", None, build_time


def deployed_by() -> str:
    try:
        user = getpass.getuser()
    except (KeyError, OSError):  # no passwd entry, e.g. in some containers
        user = "unknown"
    return f"{user}@{socket.gethostname()}"[:200]


def build_time_epoch(build_time: str | None, fallback: datetime) -> int:
    try:
        return int(parse_iso(build_time).timestamp()) if build_time else int(fallback.timestamp())
    except ValueError:
        return int(fallback.timestamp())


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="record_deploy.py",
        description="Record this build of the tracker as a deployment of itself (§15).",
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="git repository (default: .)")
    parser.add_argument(
        "--api-url", help="tracker base URL (DORA_API_URL; default http://localhost:8080)"
    )
    parser.add_argument("--api-key", help="ingest key (INGEST_API_KEY, also read from .env)")
    parser.add_argument("--service", help="service slug (DORA_SELF_SERVICE; default dora-tracker)")
    parser.add_argument(
        "--environment", default="development", choices=["development", "staging", "production"]
    )
    parser.add_argument(
        "--status", default="auto", choices=["auto", "in_progress", "succeeded", "failed"]
    )
    parser.add_argument("--started-at", help="ISO 8601 (DEPLOY_STARTED_AT; default now)")
    parser.add_argument(
        "--external-id", help="idempotency key (default local-<sha12>-<build_time_epoch>)"
    )
    parser.add_argument("--kind", default="planned", choices=["planned", "remediation"])
    parser.add_argument("--release", help="release label (default <APP_VERSION or 0.0.0>+<sha12>)")
    parser.add_argument(
        "--ensure-service",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="create the service if it's missing (default: on; CI passes --no-ensure-service)",
    )
    parser.add_argument(
        "--allow-dirty", action="store_true", help="record a dirty tree, with no commits"
    )
    parser.add_argument("--best-effort", action="store_true", help="never fail: warn and exit 0")
    parser.add_argument("--dry-run", action="store_true", help="print the payload, don't send it")
    return parser.parse_args(argv)


def record(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    settings = Settings(repo)
    git = Git(repo)
    api_key = args.api_key or settings.get("INGEST_API_KEY")
    if not api_key:
        raise RecordError("no ingest key: pass --api-key or set INGEST_API_KEY", EXIT_USAGE)
    api = Api(args.api_url or settings.get("DORA_API_URL", "http://localhost:8080") or "", api_key)
    slug = args.service or settings.get("DORA_SELF_SERVICE", "dora-tracker") or "dora-tracker"

    started_raw = args.started_at or settings.get("DEPLOY_STARTED_AT")
    try:
        started = parse_iso(started_raw) if started_raw else utc_now()
    except ValueError as exc:
        raise RecordError(f"--started-at: {exc}", EXIT_USAGE) from exc

    head = git.head()
    dirty = git.is_dirty()
    if dirty and not args.allow_dirty:
        raise RecordError(
            "the working tree has uncommitted changes, so this build isn't reproducible "
            "from its SHA; commit first, or pass --allow-dirty",
            EXIT_DIRTY,
        )

    # A dry run never writes, so it doesn't create the service either; a
    # missing service just means this would be the first recorded build.
    service_id = resolve_service(api, slug, args.ensure_service and not args.dry_run, args.dry_run)
    last = last_recorded(api, service_id, args.environment) if service_id else None

    status, suffix, build_time = (args.status, None, None)
    if args.status == "auto":
        status, suffix, build_time = check_running_build(api, head)
    elif args.external_id is None:
        _, version = api.request("GET", "/version")
        build_time = version.get("build_time")

    external_id = args.external_id or f"local-{head[:12]}-{build_time_epoch(build_time, started)}"
    if last and last.get("external_id") == external_id:
        say(f"build {external_id} is already recorded; nothing to do")
        return EXIT_OK

    if dirty:
        commits, notes = [], ["dirty tree allowed: recording without commits"]
    else:
        commits, notes = choose_commits(git, head, last)
    for note in notes:
        (warn if note.startswith(("history", "range")) else say)(note)

    base = args.release or f"{settings.get('APP_VERSION', '0.0.0')}+{head[:12]}"
    release = base + (".dirty" if dirty else "") + (f".{suffix}" if suffix else "")
    finished = utc_now()
    payload: dict[str, Any] = {
        "service_slug": slug,
        "external_id": external_id,
        "environment": args.environment,
        "kind": args.kind,
        "release": release[:100],
        "head_sha": head,
        "status": status,
        "started_at": iso(min(started, finished)),
        "deployed_by": deployed_by(),
        "commits": [c.payload() for c in commits],
    }
    if status != "in_progress":
        payload["finished_at"] = iso(finished)

    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return EXIT_OK

    code, body = api.request(
        "POST", "/api/v1/events/deployments", payload, auth=True, ok=(200, 201)
    )
    if body.get("ignored"):
        say(f"the tracker ignored this as a {body['ignored']} (an older event)")
    else:
        verb = "recorded" if code == 201 else "updated"
        count = len(commits)
        say(f"{verb} {slug} {args.environment} deployment {release} ({status}, {count} commit(s))")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return record(args)
    except RecordError as exc:
        if args.best_effort:
            warn(f"{exc} (continuing: --best-effort)")
            return EXIT_OK
        print(f"record_deploy: error: {exc}", file=sys.stderr)
        return exc.exit_code
    except Exception as exc:  # never fail a deploy job for an unexpected reason (§15.6)
        if args.best_effort:
            warn(f"unexpected {type(exc).__name__}: {exc} (continuing: --best-effort)")
            return EXIT_OK
        raise


if __name__ == "__main__":
    sys.exit(main())
