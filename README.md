# DORA Deployment Tracker

A three-tier web app that records deployments, the commits they ship, and the production failures they cause, and computes the five DORA software delivery metrics from that data. It also records its own builds, through its own API.

The design, every decision, and the build order (**BOOO**) live in [`docs/3T-APP-DESIGN.md`](docs/3T-APP-DESIGN.md). This README is the practical guide.

## Quick start

```sh
cp .env.example .env
make up        # builds and starts everything; open http://localhost:8080
make seed      # optional: 90 days of deterministic demo data for six services
```

`make up` works from a cold start with no other steps: the database initializes, migrations run, and the API and web tier wait for each other's health checks. Then it records the build (see [Self-tracking](#self-tracking)).

### Requirements

| Tool | Version | Used for |
|---|---|---|
| Docker Engine + Docker Compose v2 | tested with Engine 29.4 and Compose 5.5.1 | everything under `make up` |
| GNU Make | 3.81+ | the entry points below |
| Git | any recent | build info and self-tracking |
| [uv](https://docs.astral.sh/uv/) | 0.12+ | API lint and tests (it installs Python 3.13) |
| Node.js | 24 LTS (`nvm use` reads `.nvmrc`) | web lint, tests, and E2E |
| `python3` | 3.10+ | host scripts in `scripts/` (standard library only) |

The stack binds host ports 8080 (web), 8000 (API), and 5432 (PostgreSQL) on `127.0.0.1`; change `WEB_PORT`, `API_PORT`, or `DB_PORT_HOST` in `.env` if something else uses them.

## Architecture

```
 Browser ──► web (nginx, :8080) ── static React SPA
               │  /api/*, /healthz, /readyz, /version
               ▼
             api (FastAPI + Uvicorn, :8000) ── /metrics (Prometheus, not proxied)
               │  role dora_app: data only, no DDL
               ▼
             db (PostgreSQL 18) ◄── migrate (Alembic, one-shot, role dora_owner)
                                 ◄── seed    (demo data, one-shot, on demand)
```

Startup order is enforced by Compose: `db` healthy → `migrate` exits 0 → `api` healthy → `web`. The browser only ever talks to one origin, so there's no CORS configuration anywhere. Everything is configured through environment variables (see [`.env.example`](.env.example) and §9 of the design doc), so the same images run unchanged on AWS in Phase B.

| Tier | Stack |
|---|---|
| Web | React 19, TypeScript (strict), Vite, TanStack Query, React Router, React Hook Form + Zod, Recharts; a typed client generated from the API's OpenAPI schema |
| API | Python 3.13, FastAPI, SQLAlchemy 2 (async) + asyncpg, Pydantic v2, structlog JSON logs, Prometheus metrics |
| Data | PostgreSQL 18 (UUIDv7 keys), Alembic migrations, least-privilege roles that also work on Amazon RDS |

## Make targets

Every target is non-interactive and exits non-zero on failure, so CI can call the same ones.

| Target | What it does |
|---|---|
| `make up` | build and start the stack, wait until it's healthy, then record the build (`RECORD=0` skips that) |
| `make record-deploy` | record the running build as a `dora-tracker` deployment |
| `make down` / `make reset` | stop (keeping data) / delete all data and start cold |
| `make dev` | hot reload: API with `--reload`, Vite dev server on http://localhost:5173 |
| `make logs` | follow all logs (JSON from the API) |
| `make seed` / `make seed-large` | demo data / plus ~100k deployments for the performance check |
| `make migrate` / `make migration m="…"` | apply migrations / autogenerate a new revision |
| `make lint` / `make fmt` | ruff, mypy, eslint, prettier, tsc / auto-format |
| `make openapi` / `make openapi-check` | regenerate the API contract and TS types / fail if it drifted |
| `make test` | API, script, and web tests, then E2E |
| `make test-api` / `make test-scripts` / `make test-web` / `make e2e` | each suite on its own; reports go to `reports/` |
| `make perf` | time the org-wide 90-day DORA summary (after `make seed-large`) |
| `make build-multiarch` | build both images for `linux/amd64` and `linux/arm64` |
| `make ci` | `lint`, `openapi-check`, `test`: the single entry point for CI |

`make e2e` runs in its own Compose project (`dora-e2e`, ports 18080/18000/15432, its own volume and [env file](web/e2e/e2e.env)). It resets, seeds, tests, and tears down without touching the dev stack, which can keep running.

## The metrics

Computed for one environment (default `production`) over a window, org-wide or per service. Full definitions and edge cases are in [§3 of the design doc](docs/3T-APP-DESIGN.md#3-dora-metric-definitions).

| | Metric | In this app |
|---|---|---|
| Throughput | Deployment frequency | successful deployments that went live in the window |
| | Change lead time | median and p90 time from commit to its **first** live deployment |
| | Failed deployment recovery time | median time from detecting a failure to resolving it |
| Instability | Change fail rate | share of deployments with at least one recorded failure |
| | Deployment rework rate | share of deployments that were unplanned remediation |

A rollback is not a failure on its own: the UI asks whether to record one. An empty window shows no data rather than zeros.

> **Benchmarks are for team self-improvement, not cross-team comparison.** The elite/high/medium/low bands (`dora-2023-adapted`) are an informational aid adapted from DORA's published clusters. There is deliberately no overall grade, and rework rate has no published bands.

## Pipelines

Pipelines report deployments to `POST /api/v1/events/deployments` with an `X-API-Key`. The endpoint is idempotent on `(service, external_id)`, tolerates retries and out-of-order events, and never creates services by itself. See §7.6 of the design doc for the payload.

## Self-tracking

Every `make up` from a clean working tree records the build as a deployment of the `dora-tracker` service in the **development** environment, using [`scripts/record_deploy.py`](scripts/record_deploy.py) and the same ingest API any pipeline uses. Switch the dashboard's environment to *development* to see it.

- The first recorded build (or the first after `make reset`) records only `HEAD`; later builds record the commits since the last recorded one. A rebuild of the same commit records a deployment with no new commits.
- It records `succeeded` only if `/readyz` answers and `/version` reports exactly your `HEAD`; otherwise `failed`, so a stale container shows up as a failure rather than a false success.
- A working tree with uncommitted changes isn't recorded (its build can't be reproduced from a SHA). `make up` just warns; `python3 scripts/record_deploy.py --allow-dirty` records it without commits.
- Recording never fails `make up`. Rerunning it for the same build changes nothing.
- These numbers mean "commit → running on my laptop": useful dogfooding, not a delivery-performance signal. In Phase B, the deploy pipeline runs the same script against real environments.

`make e2e` runs in its own stack, so it never touches this history; `make reset` does erase it.

## Testing

| Suite | Tool | Notes |
|---|---|---|
| API unit + integration | pytest against real PostgreSQL 18 (Testcontainers) | includes golden datasets A–C for the metrics engine; coverage ≥ 80% enforced |
| Scripts | pytest with throwaway git repos and a fake API, on **Python 3.10** | `record_deploy.py`: commit ranges, dirty trees, status, idempotency, failures |
| Web | Vitest + Testing Library | components, forms, error handling, conflicts; runs in a US Pacific time zone to catch UTC bugs |
| E2E | Playwright | the ten scenarios in §12.4 of the design doc |

## Performance

`make seed-large` then `make perf`, on an Apple M2 (OrbStack), 100,221 deployments (87,882 counted in the 90-day window):

| Endpoint | p50 | p95 | Target |
|---|---|---|---|
| `/api/v1/metrics/dora` (org-wide, 90 days) | 250 ms | **272 ms** | p95 < 500 ms |
| `/api/v1/metrics/dora/timeseries` (weekly) | 307 ms | 330 ms | — |

## Branches

All work happens on `dev`. `stage` and `prod` only change through pull requests (dev → stage → prod), and `main` holds only the GitHub Actions workflows for Phase B.
