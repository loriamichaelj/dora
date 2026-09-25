# DORA Deployment Tracker — local entry points (§10).
# Every target is non-interactive, needs no TTY, and exits non-zero on
# failure, so GitHub Actions can call the same targets unchanged.

SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE ?= docker compose
UV := uv run --locked
REPORTS := $(CURDIR)/reports

# Build info, captured once at parse time (before any build starts) and
# passed to `docker compose build` through build.args interpolation.
ifeq ($(origin GIT_SHA), undefined)
GIT_SHA := $(shell git rev-parse HEAD 2>/dev/null || echo unknown)
endif
ifeq ($(origin BUILD_TIME), undefined)
BUILD_TIME := $(shell date -u +%Y-%m-%dT%H:%M:%SZ)
endif
ifeq ($(origin APP_VERSION), undefined)
APP_VERSION := $(shell sed -n 's/^version = "\(.*\)"/\1/p' api/pyproject.toml)
endif
ifeq ($(origin DEPLOY_STARTED_AT), undefined)
DEPLOY_STARTED_AT := $(BUILD_TIME)
endif
export GIT_SHA BUILD_TIME APP_VERSION DEPLOY_STARTED_AT

.PHONY: help up down reset logs migrate migration seed seed-large analyze perf lint lint-api \
        lint-web fmt test test-api test-web ci check-env check-node

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-14s %s\n", $$1, $$2}'

# ---- stack ----

up: check-env ## Build and start the stack, wait until web is healthy
	$(COMPOSE) up -d --build --wait web

down: ## Stop the stack, keep data
	$(COMPOSE) down

reset: check-env ## Delete all data (volumes), then start from cold
	$(COMPOSE) down -v --remove-orphans
	$(MAKE) up

logs: ## Follow logs from all services
	$(COMPOSE) logs -f

# ---- database ----

migrate: check-env ## Apply migrations (alembic upgrade head)
	$(COMPOSE) run --rm --build migrate

migration: check-env ## Autogenerate a revision: make migration m="add foo"
	@test -n "$(m)" || { echo 'usage: make migration m="message"' >&2; exit 1; }
	$(COMPOSE) run --rm --build -v $(CURDIR)/api/alembic/versions:/app/alembic/versions \
		migrate alembic revision --autogenerate -m "$(m)"

seed: check-env ## Load deterministic demo data (replaces earlier seed data)
	$(COMPOSE) --profile seed run --rm --build seed
	$(MAKE) --no-print-directory analyze

seed-large: check-env ## Demo data plus ~100k deployments for the performance check
	$(COMPOSE) --profile seed run --rm --build seed \
		python -m app.seed --days 90 --seed 42 --large
	$(MAKE) --no-print-directory analyze

# The app role can't ANALYZE tables it doesn't own; refresh planner statistics
# as postgres after a bulk load so the first queries get good plans.
analyze:
	$(COMPOSE) exec -T db psql -U postgres -d dora -qc 'ANALYZE dora.services, dora.deployments, dora.commits, dora.deployment_commits, dora.failures'

perf: ## Time the org-wide 90-day DORA summary (run after seed-large)
	python3 scripts/perf_check.py

# ---- quality ----

lint: lint-api lint-web ## ruff, mypy, eslint, prettier, tsc

lint-api:
	cd api && $(UV) ruff check .
	cd api && $(UV) ruff format --check .
	cd api && $(UV) mypy

lint-web: check-node web/node_modules/.package-lock.json
	cd web && npm run --silent lint
	cd web && npm run --silent format:check
	cd web && npm run --silent typecheck

fmt: check-node web/node_modules/.package-lock.json ## Auto-format api and web
	cd api && $(UV) ruff check --fix .
	cd api && $(UV) ruff format .
	cd web && npm run --silent format

# ---- tests ----

test: test-api test-web ## All test suites

test-api: ## pytest + coverage -> reports/
	@mkdir -p $(REPORTS)
	cd api && $(UV) pytest --cov --cov-report=term-missing:skip-covered \
		--cov-report=xml:$(REPORTS)/coverage-api.xml --cov-fail-under=80 \
		--junitxml=$(REPORTS)/junit-api.xml

test-web: check-node web/node_modules/.package-lock.json ## Vitest -> reports/
	@mkdir -p $(REPORTS)
	cd web && npx vitest run --reporter=default --reporter=junit \
		--outputFile.junit=$(REPORTS)/junit-web.xml

ci: lint test ## Single entry point for CI

# ---- helpers ----

web/node_modules/.package-lock.json: web/package.json web/package-lock.json
	cd web && npm ci --no-audit --no-fund

check-env:
	@test -f .env || { echo "error: .env is missing. Run: cp .env.example .env" >&2; exit 1; }

check-node:
	@node -e 'process.exit(process.versions.node.split(".")[0] === "24" ? 0 : 1)' 2>/dev/null || \
		{ echo "error: Node 24 is required (found $$(node --version 2>/dev/null || echo none)). Run: nvm use" >&2; exit 1; }
