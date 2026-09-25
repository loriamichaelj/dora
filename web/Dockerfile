# syntax=docker/dockerfile:1

# ---- build: compile the static SPA ----
FROM node:24.21.0-trixie-slim AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# ---- runtime: static files behind nginx, non-root on 8080 ----
FROM nginxinc/nginx-unprivileged:1.30.5-alpine AS runtime

ARG APP_VERSION=unknown
ARG GIT_SHA=unknown
ARG BUILD_TIME=unknown
ARG SOURCE_URL=https://github.com/loriamichaelj/dora

LABEL org.opencontainers.image.title="dora-web" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.created="${BUILD_TIME}" \
      org.opencontainers.image.source="${SOURCE_URL}"

ENV API_UPSTREAM=api:8000

COPY nginx/templates/ /etc/nginx/templates/
COPY --from=build /web/dist/ /usr/share/nginx/html/

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/index.html"]
