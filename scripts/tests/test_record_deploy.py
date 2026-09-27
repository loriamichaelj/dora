"""record_deploy.py (§15, §12 "Self-tracking script" row)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pytest
from conftest import API_KEY, FakeTracker, Repo

import record_deploy as rd


def run(tracker: FakeTracker, repo: Repo, *extra: str) -> int:
    return rd.main(
        ["--repo", str(repo.path), "--api-url", tracker.url, "--api-key", API_KEY, *extra]
    )


def build(tracker: FakeTracker, repo: Repo, build_time: str = "2026-09-25T12:00:00Z") -> None:
    """Pretend the running stack was just built from the repo's HEAD."""
    tracker.version.update(git_sha=repo.head(), build_time=build_time)


def recorded(tracker: FakeTracker) -> list[dict[str, Any]]:
    return tracker.deployments_for("dora-tracker")


# ---- commit range (§15.3) ----


def test_first_run_records_only_head_and_creates_the_service(
    tracker: FakeTracker, repo: Repo
) -> None:
    repo.commit("feat: a")
    head = repo.commit("feat: b")
    build(tracker, repo)

    assert run(tracker, repo) == 0
    [service] = tracker.services
    assert service["slug"] == "dora-tracker"
    [deployment] = recorded(tracker)
    assert deployment["head_sha"] == head
    assert [c["sha"] for c in deployment["commits"]] == [head]
    assert deployment["commits"][0]["message"] == "feat: b"
    assert deployment["commits"][0]["author"] == "dev@example.com"


def test_next_run_records_the_commits_since_the_last_build(
    tracker: FakeTracker, repo: Repo
) -> None:
    build(tracker, repo)
    assert run(tracker, repo) == 0
    c1, c2 = repo.commit("fix: one"), repo.commit("fix: two")
    build(tracker, repo, "2026-09-25T13:00:00Z")

    assert run(tracker, repo) == 0
    latest = recorded(tracker)[-1]
    assert [c["sha"] for c in latest["commits"]] == [c2, c1]  # newest first, like git log


def test_a_rebuild_of_the_same_head_records_no_commits(tracker: FakeTracker, repo: Repo) -> None:
    build(tracker, repo)
    run(tracker, repo)
    build(tracker, repo, "2026-09-25T14:00:00Z")  # same commit, new image

    assert run(tracker, repo) == 0
    assert len(recorded(tracker)) == 2
    assert recorded(tracker)[-1]["commits"] == []


def test_a_rollback_to_an_older_commit_records_no_commits(
    tracker: FakeTracker, repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    old = repo.head()
    build(tracker, repo)
    run(tracker, repo)
    repo.commit("feat: newer")
    build(tracker, repo, "2026-09-25T13:00:00Z")
    run(tracker, repo)
    recorded(tracker)[-1]["finished_at"] = "2099-01-01T00:00:00Z"  # the latest build
    repo.git("checkout", "-q", old)  # roll back: deploy the older commit again
    build(tracker, repo, "2026-09-25T14:00:00Z")

    assert run(tracker, repo) == 0
    out = capsys.readouterr().out
    assert "older than the last recorded build" in out
    assert "history was rewritten" not in out
    assert recorded(tracker)[-1]["head_sha"] == old
    assert recorded(tracker)[-1]["commits"] == []


def test_rewritten_history_falls_back_to_commits_since_the_last_build(
    tracker: FakeTracker, repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    repo.commit("feat: will be rewritten")
    build(tracker, repo)
    run(tracker, repo)
    repo.git("reset", "-q", "--hard", "HEAD~1")  # the recorded SHA leaves the branch
    new = repo.commit("feat: rewritten")
    build(tracker, repo, "2026-09-25T15:00:00Z")
    recorded(tracker)[0]["finished_at"] = "2000-01-01T00:00:00Z"  # everything is "since"

    assert run(tracker, repo) == 0
    assert "history was rewritten" in capsys.readouterr().err
    shas = [c["sha"] for c in recorded(tracker)[-1]["commits"]]
    assert shas[0] == new
    assert len(shas) == 2  # the rewritten commit and the initial one


def test_the_range_is_capped(
    tracker: FakeTracker,
    repo: Repo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(rd, "MAX_COMMITS", 3)
    build(tracker, repo)
    run(tracker, repo)
    for i in range(5):
        repo.commit(f"chore: {i}")
    build(tracker, repo, "2026-09-25T16:00:00Z")

    assert run(tracker, repo) == 0
    assert len(recorded(tracker)[-1]["commits"]) == 3
    assert "truncated" in capsys.readouterr().err


# ---- payload and idempotency ----


def test_payload_shape(
    tracker: FakeTracker, repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    build(tracker, repo)
    head = repo.head()
    assert run(tracker, repo, "--dry-run", "--started-at", "2026-09-25T11:55:00Z") == 0
    out = capsys.readouterr().out
    payload = json.loads(out[out.index("{") :])
    epoch = int(datetime(2026, 9, 25, 12, tzinfo=timezone.utc).timestamp())  # /version build_time
    assert payload == {
        "service_slug": "dora-tracker",
        "external_id": f"local-{head[:12]}-{epoch}",
        "environment": "development",
        "kind": "planned",
        "release": f"0.0.0+{head[:12]}",
        "head_sha": head,
        "status": "succeeded",
        "started_at": "2026-09-25T11:55:00Z",
        "finished_at": payload["finished_at"],
        "deployed_by": payload["deployed_by"],
        "commits": [payload["commits"][0]],
    }
    assert payload["finished_at"].endswith("Z")
    assert tracker.deployments == []  # a dry run sends nothing...
    assert tracker.services == []  # ...and creates nothing
    assert "a real run would create it" in out


def test_app_version_becomes_the_release(
    tracker: FakeTracker, repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_VERSION", "0.1.0")
    build(tracker, repo)
    run(tracker, repo)
    assert recorded(tracker)[0]["release"] == f"0.1.0+{repo.head()[:12]}"


def test_running_twice_for_the_same_build_is_a_no_op(
    tracker: FakeTracker, repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    build(tracker, repo)
    assert run(tracker, repo) == 0
    before = [dict(d) for d in recorded(tracker)]
    assert run(tracker, repo) == 0
    assert recorded(tracker) == before
    assert "already recorded" in capsys.readouterr().out


def test_in_progress_then_succeeded_with_an_explicit_external_id(
    tracker: FakeTracker, repo: Repo
) -> None:
    """The Phase B shape: two events for one pipeline run (§15.6)."""
    build(tracker, repo)
    args = ("--external-id", "gha-42-1-production", "--environment", "production")
    assert run(tracker, repo, *args, "--status", "in_progress") == 0
    [deployment] = tracker.deployments_for("dora-tracker")
    assert deployment["status"] == "in_progress"
    assert "finished_at" not in deployment

    assert run(tracker, repo, *args, "--status", "succeeded") == 0
    [deployment] = tracker.deployments_for("dora-tracker")
    assert deployment["status"] == "succeeded"
    assert deployment["finished_at"]


# ---- status (§15.4) ----


def test_sha_mismatch_records_failed(tracker: FakeTracker, repo: Repo) -> None:
    tracker.version.update(git_sha="f" * 40)
    assert run(tracker, repo) == 0
    [deployment] = recorded(tracker)
    assert deployment["status"] == "failed"
    assert deployment["release"].endswith(".sha-mismatch")


def test_not_ready_records_failed(tracker: FakeTracker, repo: Repo) -> None:
    build(tracker, repo)
    tracker.ready = False
    assert run(tracker, repo) == 0
    assert recorded(tracker)[0]["status"] == "failed"
    assert recorded(tracker)[0]["release"].endswith(".not-ready")


# ---- dirty trees and failures ----


def test_a_dirty_tree_is_refused(tracker: FakeTracker, repo: Repo) -> None:
    build(tracker, repo)
    (repo.path / "uncommitted.txt").write_text("wip")
    assert run(tracker, repo) == rd.EXIT_DIRTY
    assert tracker.deployments == []
    assert run(tracker, repo, "--best-effort") == 0  # warns, skips, never fails `make up`
    assert tracker.deployments == []


def test_allow_dirty_records_without_commits(tracker: FakeTracker, repo: Repo) -> None:
    build(tracker, repo)
    (repo.path / "uncommitted.txt").write_text("wip")
    assert run(tracker, repo, "--allow-dirty") == 0
    [deployment] = recorded(tracker)
    assert deployment["commits"] == []
    assert ".dirty" in deployment["release"]


def test_unreachable_api(
    repo: Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(rd.time, "sleep", lambda _s: None)  # skip backoff waits
    args = ["--repo", str(repo.path), "--api-url", "http://127.0.0.1:9", "--api-key", API_KEY]
    assert rd.main(args) == rd.EXIT_API
    assert rd.main([*args, "--best-effort"]) == 0
    assert "unreachable" in capsys.readouterr().err


def test_missing_key_is_a_usage_error(tracker: FakeTracker, repo: Repo) -> None:
    assert rd.main(["--repo", str(repo.path), "--api-url", tracker.url]) == rd.EXIT_USAGE


def test_key_and_url_come_from_dotenv(tracker: FakeTracker, repo: Repo) -> None:
    (repo.path / ".env").write_text(f"INGEST_API_KEY={API_KEY}\nDORA_API_URL={tracker.url}\n")
    repo.git("add", ".env")
    repo.git("commit", "-q", "-m", "test env")  # keep the tree clean
    build(tracker, repo)
    assert rd.main(["--repo", str(repo.path)]) == 0
    assert len(recorded(tracker)) == 1


def test_no_ensure_service_fails_when_missing(tracker: FakeTracker, repo: Repo) -> None:
    build(tracker, repo)
    assert run(tracker, repo, "--no-ensure-service") == rd.EXIT_API
    assert tracker.services == []


def test_non_http_urls_are_rejected(repo: Repo) -> None:
    args = ["--repo", str(repo.path), "--api-url", "file:///etc/passwd", "--api-key", API_KEY]
    assert rd.main(args) == rd.EXIT_USAGE
