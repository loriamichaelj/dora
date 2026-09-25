import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.config import Settings


async def test_healthz_is_ok(client: AsyncClient) -> None:
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_version_reports_build_info(client: AsyncClient) -> None:
    resp = await client.get("/version")
    assert resp.status_code == 200
    assert resp.json() == {
        "version": "0.0.0-test",
        "git_sha": "0" * 40,
        "build_time": "2026-01-01T00:00:00Z",
    }


@pytest.mark.parametrize("key", [None, "", "too-short"])
def test_settings_reject_missing_or_short_ingest_key(
    monkeypatch: pytest.MonkeyPatch, key: str | None
) -> None:
    if key is None:
        monkeypatch.delenv("INGEST_API_KEY", raising=False)
    else:
        monkeypatch.setenv("INGEST_API_KEY", key)
    with pytest.raises(ValidationError):
        Settings()


def test_build_info_defaults_to_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("APP_VERSION", "GIT_SHA", "BUILD_TIME"):
        monkeypatch.delenv(var, raising=False)
    settings = Settings()
    assert (settings.app_version, settings.git_sha, settings.build_time) == ("unknown",) * 3
