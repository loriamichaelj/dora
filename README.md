# DORA Deployment Tracker

A three-tier web app that records deployments, the commits they ship, and the production failures they cause, and computes the five DORA software delivery metrics from that data. It also records its own builds and deploys, through its own API.

It runs locally with Docker Compose, and on AWS (ECS on Fargate, RDS, GitHub Actions with OIDC) in a **dev** environment: http://loria-dora-dev-alb-1183097088.us-east-1.elb.amazonaws.com.

> **You're on `main`, which holds only the GitHub Actions workflows.** The app, its infrastructure, and all the documentation live on the [`dev`](https://github.com/loriamichaelj/dora/tree/dev) branch. Start with its [README](https://github.com/loriamichaelj/dora/blob/dev/README.md).

## What it does

It computes the five DORA metrics for an environment over a window, org-wide or per service:

| | Metric |
|---|---|
| Throughput | Deployment frequency, change lead time, failed deployment recovery time |
| Instability | Change fail rate, deployment rework rate |

Pipelines report deployments to an idempotent ingest API, and people record failures and rollbacks in the UI. The dashboard shows each metric against benchmark bands adapted from DORA's published clusters, meant for a team's own improvement rather than for comparing teams.

## How it's built

| Tier | Stack |
|---|---|
| Web | React 19, TypeScript, Vite, TanStack Query, Recharts, served by nginx |
| API | Python 3.13, FastAPI, SQLAlchemy 2 (async), Pydantic v2, Prometheus metrics |
| Data | PostgreSQL 18, Alembic migrations, least-privilege roles |
| AWS | ECS on Fargate (ARM64) behind an ALB, RDS PostgreSQL, ECR, VPC endpoints instead of internet egress, all in Terraform |
| Pipeline | GitHub Actions with OIDC (no AWS keys anywhere), images built once per release and reused by every deploy and rollback |

## Branches

| Branch | Holds |
|---|---|
| [`dev`](https://github.com/loriamichaelj/dora/tree/dev) | all development: the app, Terraform, scripts, and docs |
| `stage`, `prod` | changed only by pull requests, dev → stage → prod (designed; only dev is provisioned) |
| `main` | the GitHub Actions workflows, each changed by a PR from a `workflows/<name>` branch |

Every workflow's logic lives here as a reusable workflow; thin trigger stubs on `dev` call them with an explicit `ref`.

| Workflow | Does |
|---|---|
| [`test.yml`](.github/workflows/test.yml) | `make ci` (lint, OpenAPI drift check, unit, integration, and E2E tests) on every push to `dev` |
| [`deploy.yml`](.github/workflows/deploy.yml) | builds the images once, then preflight, database bootstrap, migrations, a rolling update, smoke tests, and records the deploy in the app itself |
| [`rollback.yml`](.github/workflows/rollback.yml) | rolls back to an earlier release, with its rules checked first and a dry run |
| [`seed.yml`](.github/workflows/seed.yml) | loads demo data |
| [`terraform.yml`](.github/workflows/terraform.yml), [`bootstrap.yml`](.github/workflows/bootstrap.yml) | plan, apply, or destroy the Terraform roots |
| [`ci.yml`](.github/workflows/ci.yml) | lints the workflows on every PR into `main` |

## Documentation (on `dev`)

| Document | What's in it |
|---|---|
| [README](https://github.com/loriamichaelj/dora/blob/dev/README.md) | Quick start, architecture, Make targets, testing, and performance |
| [`3T-APP-DESIGN.md`](https://github.com/loriamichaelj/dora/blob/dev/docs/3T-APP-DESIGN.md) | The app: design, decisions, and build order |
| [`CLOUD-DEVOPS-DESIGN.md`](https://github.com/loriamichaelj/dora/blob/dev/docs/CLOUD-DEVOPS-DESIGN.md) | AWS and the pipeline: design, decisions, and build order |
| [`RUNBOOK.md`](https://github.com/loriamichaelj/dora/blob/dev/docs/RUNBOOK.md) | Operating it on AWS: deploy, roll back, seed, failed pipelines, cost |

Releases are published on GitHub; the latest official one is [`release-c225e7a93a13`](https://github.com/loriamichaelj/dora/releases/latest).
