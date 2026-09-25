"""Container entrypoint: `python -m app`.

Runs Uvicorn in-process so PORT and FORWARDED_ALLOW_IPS come from settings
while the image keeps an exec-form CMD (Python is PID 1 and gets SIGTERM).
"""

import uvicorn

from app.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",  # noqa: S104  # bind address is always 0.0.0.0 (§9)
        port=settings.port,
        proxy_headers=True,
        forwarded_allow_ips=settings.forwarded_allow_ips,
        timeout_graceful_shutdown=20,
        access_log=False,  # RequestContextMiddleware writes the access log
        server_header=False,
        log_config=None,  # keep app.logging's JSON configuration
    )


if __name__ == "__main__":
    main()
