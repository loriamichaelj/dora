# DORA Deployment Tracker — local entry points (§10).
# Every target is non-interactive, needs no TTY, and exits non-zero on
# failure, so GitHub Actions can call the same targets unchanged.

SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE ?= docker compose
UV := uv run --locked
REPORTS := $(CURDIR)/reports
OPENAPI_JSON := web/src/api/openapi.json
SCHEMA_TS := web/src/api/schema.d.ts

# The isolated E2E stack (§10, §15.5): its own project name, volume, ports,
# and env file, so it never touches the dev stack's data or reads .env.
E2E_ENV := web/e2e/e2e.env
E2E_COMPOSE := $(COMPOSE) -p dora-e2e --env-file $(E2E_ENV) -f compose.yaml

# Host scripts are standard library only and must run on Python 3.10 (D58),
# so their lint and tests run on exactly that version, outside the api venv.
RUFF_VERSION := 0.16.9
SCRIPTS_PY := uv run --no-project --python 3.10
RECORD ?= 1

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
        lint-scripts test-scripts record-deploy \
        lint-web fmt test test-api test-web e2e e2e-browsers openapi openapi-check ci \
        build-multiarch dev check-env check-node

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-14s %s\n", $$1, $$2}'

# ---- stack ----

up: check-env ## Build and start the stack, then record the build (RECORD=0 to skip)
	$(COMPOSE) up -d --build --wait web
	@if [ "$(RECORD)" != "0" ]; then \
		python3 scripts/record_deploy.py --best-effort --started-at "$(DEPLOY_STARTED_AT)"; \
	fi

record-deploy: ## Record the running build as a dora-tracker deployment (§15)
	python3 scripts/record_deploy.py

down: ## Stop the stack, keep data
	$(COMPOSE) down

reset: check-env ## Delete all data (volumes), then start from cold
	$(COMPOSE) down -v --remove-orphans
	$(MAKE) up

logs: ## Follow logs from all services
	$(COMPOSE) logs -f

dev: check-env ## Hot reload: api --reload, Vite dev server on :5173
	$(COMPOSE) -f compose.yaml -f compose.dev.yaml up --build

# Both images must build for amd64 and arm64 (§10, §16). The default docker
# driver can't build multi-platform images, so use a docker-container builder,
# created once. --output type=cacheonly builds without loading or pushing.
MULTIARCH_BUILDER := dora-multiarch
build-multiarch: ## Build the api, web, and dbinit images for linux/amd64 and linux/arm64
	docker buildx inspect $(MULTIARCH_BUILDER) >/dev/null 2>&1 || \
		docker buildx create --name $(MULTIARCH_BUILDER) --driver docker-container >/dev/null
	docker buildx build --builder $(MULTIARCH_BUILDER) --platform linux/amd64,linux/arm64 \
		--output type=cacheonly ./api
	docker buildx build --builder $(MULTIARCH_BUILDER) --platform linux/amd64,linux/arm64 \
		--output type=cacheonly ./web
	docker buildx build --builder $(MULTIARCH_BUILDER) --platform linux/amd64,linux/arm64 \
		--output type=cacheonly ./db

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

lint: lint-api lint-web lint-scripts ## ruff, mypy, eslint, prettier, tsc

lint-api:
	cd api && $(UV) ruff check .
	cd api && $(UV) ruff format --check .
	cd api && $(UV) mypy

lint-scripts:
	cd scripts && uvx ruff@$(RUFF_VERSION) check .
	cd scripts && uvx ruff@$(RUFF_VERSION) format --check .

lint-web: check-node web/node_modules/.package-lock.json
	cd web && npm run --silent lint
	cd web && npm run --silent format:check
	cd web && npm run --silent typecheck

fmt: check-node web/node_modules/.package-lock.json ## Auto-format api and web
	cd api && $(UV) ruff check --fix .
	cd api && $(UV) ruff format .
	cd web && npm run --silent format

# ---- API contract ----

# Exported without starting a server. The placeholder key only satisfies the
# settings check; nothing is served. openapi-typescript runs from its own
# package (web/tools/openapi) because it needs TypeScript 5 and the app uses 6.
openapi: check-node web/tools/openapi/node_modules/.package-lock.json ## Regenerate the OpenAPI schema and TS types
	cd api && INGEST_API_KEY=openapi-export-placeholder-000000000000 $(UV) python -c \
		'import json; from app.main import app; open("../$(OPENAPI_JSON)", "w").write(json.dumps(app.openapi(), indent=2) + "\n")'
	cd web/tools/openapi && npx --no-install openapi-typescript ../../src/api/openapi.json \
		-o ../../src/api/schema.d.ts --silent

# Compares the regenerated files with the index (committed or staged), so on a
# fresh CI checkout this is a comparison with HEAD.
openapi-check: openapi ## Fail if the committed API contract is out of date
	@if ! git diff --quiet -- $(OPENAPI_JSON) $(SCHEMA_TS) || \
		[ -n "$$(git ls-files --others --exclude-standard -- $(OPENAPI_JSON) $(SCHEMA_TS))" ]; then \
		git --no-pager diff --stat -- $(OPENAPI_JSON) $(SCHEMA_TS); \
		echo "error: the API contract changed; run 'make openapi' and commit the result" >&2; exit 1; \
	fi

# ---- tests ----

test: test-api test-scripts test-web e2e ## All test suites: api, scripts, web, then E2E

test-scripts: ## Host script tests (record_deploy, scripts/deploy) on Python 3.10 -> reports/
	@mkdir -p $(REPORTS)
	$(SCRIPTS_PY) --with pytest==9.1.1 pytest scripts/tests -q -p no:cacheprovider \
		--junitxml=$(REPORTS)/junit-scripts.xml

test-api: ## pytest + coverage -> reports/
	@mkdir -p $(REPORTS)
	cd api && $(UV) pytest --cov --cov-report=term-missing:skip-covered \
		--cov-report=xml:$(REPORTS)/coverage-api.xml --cov-fail-under=80 \
		--junitxml=$(REPORTS)/junit-api.xml

test-web: check-node web/node_modules/.package-lock.json ## Vitest -> reports/
	@mkdir -p $(REPORTS)
	cd web && npx vitest run --reporter=default --reporter=junit \
		--outputFile.junit=$(REPORTS)/junit-web.xml

# ---- E2E ----

e2e-browsers: check-node web/node_modules/.package-lock.json
	cd web && npx playwright install chromium

# Cold start from an empty volume, seed, run Playwright, and always tear down,
# keeping Playwright's exit code. Traces and screenshots of failures are kept
# in reports/playwright/.
e2e: check-node web/node_modules/.package-lock.json e2e-browsers ## Playwright E2E in the isolated dora-e2e stack
	@mkdir -p $(REPORTS)
	$(E2E_COMPOSE) down -v --remove-orphans
	$(E2E_COMPOSE) up -d --build --wait web
	$(E2E_COMPOSE) --profile seed run --rm --build seed
	$(E2E_COMPOSE) exec -T db psql -U postgres -d dora -qc 'ANALYZE'
	@status=0; \
		(cd web && E2E_BASE_URL=http://localhost:18080 npx playwright test) || status=$$?; \
		if [ $$status -eq 0 ]; then \
			echo "e2e: rerun the db bootstrap with the dbinit image (idempotent: must succeed again)"; \
			$(E2E_COMPOSE) --profile dbinit run --rm --build dbinit || status=$$?; \
		fi; \
		if [ $$status -eq 0 ]; then \
			echo "e2e: the RDS CA bundle loads as each image's non-root user"; \
			docker run --rm --entrypoint python dora-api:local -c \
				"import ssl; ssl.create_default_context(cafile='/etc/ssl/rds/global-bundle.pem')" \
				|| status=$$?; \
			docker run --rm --entrypoint sh dora-dbinit:local -c \
				'openssl x509 -noout -in /etc/ssl/rds/global-bundle.pem' || status=$$?; \
		fi; \
		if [ $$status -eq 0 ]; then \
			python3 scripts/deploy/smoke_test.py --base-url http://localhost:18080 \
				--git-sha "$(GIT_SHA)" --ready-attempts 5 --ready-delay 2 || status=$$?; \
		fi; \
		$(E2E_COMPOSE) down -v --remove-orphans; \
		exit $$status

ci: lint openapi-check test ## Single entry point for CI

# ---- helpers ----

web/node_modules/.package-lock.json: web/package.json web/package-lock.json
	cd web && npm ci --no-audit --no-fund

web/tools/openapi/node_modules/.package-lock.json: web/tools/openapi/package.json web/tools/openapi/package-lock.json
	cd web/tools/openapi && npm ci --no-audit --no-fund

check-env:
	@test -f .env || { echo "error: .env is missing. Run: cp .env.example .env" >&2; exit 1; }

check-node:
	@node -e 'process.exit(process.versions.node.split(".")[0] === "24" ? 0 : 1)' 2>/dev/null || \
		{ echo "error: Node 24 is required (found $$(node --version 2>/dev/null || echo none)). Run: nvm use" >&2; exit 1; }
