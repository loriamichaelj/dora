# deploy/ecs

ECS task-definition templates (docs/CLOUD-DEVOPS-DESIGN.md §6.4, §6.8, §7.3). They are
versioned with the code, so a new environment variable ships with the release that needs it.
`scripts/deploy/ecs_deploy.py register` renders one and registers it as a new revision.

| Template | Family | Image | Runs as (database) | Execution role reads |
|---|---|---|---|---|
| `app.json.tmpl` | `<prefix>-<env>-app` | `api` + `web` | `dora_app` | `db-app`, `ingest-api-key` |
| `migrate.json.tmpl` | `<prefix>-<env>-migrate` | `api` | `dora_owner` | `db-owner` |
| `seed.json.tmpl` | `<prefix>-<env>-seed` | `api` | `dora_app` | `db-app` |
| `db-bootstrap.json.tmpl` | `<prefix>-<env>-db-bootstrap` | `dbinit` | RDS master user | the RDS master secret, `db-owner`, `db-app` |

Every template:

- is Fargate, `awsvpc`, ARM64;
- references images by digest (`repo@sha256:…`), never by tag;
- connects to the database with `verify-full`, trusting the RDS CA bundle baked into the
  image at `/etc/ssl/rds/global-bundle.pem`;
- logs through `awslogs` with the container name as stream prefix, so a task's stream is
  `<container>/<container>/<task-id>`;
- carries the `Project` and `Environment` tags, without which the deploy role may not register
  it (`infra/bootstrap/iam.tf`), plus `ManagedBy=deploy` and `Release=<version>`.

In `app`, `web` starts only once `api` is healthy, and its nginx proxies to
`127.0.0.1:8000`. Only `web` has a port mapping; the ALB reaches it on 8080. The `api`
container's health check is `/healthz`, never `/readyz` (C5).

## Placeholders

`${NAME}` placeholders are filled by `ecs_deploy.py` from three sources:

| Source | Placeholders |
|---|---|
| The workflow's environment (`infra/project.env`, the target environment) | `NAME_PREFIX`, `ENVIRONMENT`, `AWS_REGION` |
| The release (preflight's output) | `RELEASE_VERSION`, `API_IMAGE`, `WEB_IMAGE`, `DBINIT_IMAGE` |
| `deploy-config`, below | every key, upper-cased |

A missing placeholder fails the render, naming it.

## The `deploy-config` contract

`infra/env` publishes one JSON document per environment to the SSM parameter
`/<name_prefix>/<env>/deploy-config`. Every key is required; `ecs_deploy.py` refuses to
run if one is missing.

| Key | Example (dev) | Used for |
|---|---|---|
| `cluster` | `loria-dora-dev` | every ECS call |
| `service` | `loria-dora-dev-app` | rollout |
| `subnets` | `["subnet-…", "subnet-…"]` (dev's private subnets) | one-off tasks |
| `security_group` | `sg-…` (the task security group) | one-off tasks |
| `desired_count` | `1` | the first rollout, which scales the service up from 0 |
| `cpu`, `memory` | `"512"`, `"1024"` | the `app` task size |
| `task_role_arn` | `…:role/cloudbatch818-loria-dora-dev-task` | every task (it grants nothing: the app calls no AWS API) |
| `execution_role_arn` | `…:role/cloudbatch818-loria-dora-dev-task-exec` | `app`, `migrate`, `seed`: pull images, write logs, read their secrets |
| `db_bootstrap_execution_role_arn` | `…:role/cloudbatch818-loria-dora-dev-db-bootstrap-exec` | `db-bootstrap` only: also reads the master secret |
| `app_log_group`, `jobs_log_group` | `/loria-dora/dev/app`, `/loria-dora/dev/jobs` | log configuration |
| `db_host`, `db_port`, `db_name` | the RDS endpoint, `5432`, `dora` | database connection |
| `db_master_secret_arn` | the RDS-managed `rds!db-…` secret | `db-bootstrap` |
| `db_owner_secret_arn`, `db_app_secret_arn` | `loria-dora/dev/db-owner`, `…/db-app` (JSON `{username, password}`) | the database passwords |
| `ingest_api_key_secret_arn` | `loria-dora/dev/ingest-api-key` (a plain string) | `INGEST_API_KEY` |
| `alb_dns_name` | `loria-dora-dev-alb-….elb.amazonaws.com` | smoke tests and self-tracking |

Both execution roles and the task role carry the permissions boundary
`cloudbatch818-loria-dora-task-boundary`.
