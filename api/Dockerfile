# syntax=docker/dockerfile:1

ARG PYTHON_IMAGE=python:3.13.15-slim-trixie

FROM ghcr.io/astral-sh/uv:0.12.15 AS uv

# ---- build: resolve the locked runtime dependencies into /app/.venv ----
FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

# ---- runtime ----
FROM ${PYTHON_IMAGE} AS runtime

ARG APP_VERSION=unknown
ARG GIT_SHA=unknown
ARG BUILD_TIME=unknown
ARG SOURCE_URL=https://github.com/loriamichaelj/dora

LABEL org.opencontainers.image.title="dora-api" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.created="${BUILD_TIME}" \
      org.opencontainers.image.source="${SOURCE_URL}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}" \
    APP_VERSION=${APP_VERSION} \
    GIT_SHA=${GIT_SHA} \
    BUILD_TIME=${BUILD_TIME} \
    PORT=8000

RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY app ./app

USER 10001:10001
EXPOSE 8000

# Liveness only (§10, D1). Slim images have no curl, so use the stdlib.
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/healthz', timeout=2)"]

CMD ["python", "-m", "app"]
