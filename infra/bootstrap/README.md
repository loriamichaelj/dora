# infra/bootstrap

Account-wide foundations for Dora (see `docs/CLOUD-DEVOPS-DESIGN.md` §5.2):

- the Terraform state bucket, `loria-dora-tfstate-<account-id>`
- the shared ECR repositories `loria-dora/api`, `loria-dora/web`, and `loria-dora/dbinit`
- the four GitHub Actions deploy roles: `cloudbatch818-loria-dora-deploy-{dev,stage,prod,shared}`
- `cloudbatch818-loria-dora-task-boundary`, the permissions boundary on every ECS task and task execution role

Names come from [`infra/project.env`](../project.env). The AWS account is shared with Beacon, so
every name carries a project prefix, and IAM names must start with `cloudbatch818-`.

All AWS access runs through GitHub Actions. This root is only ever applied by the
`bootstrap.yml` workflow on `main`, never from a laptop.

**State:** Applied 2026-09-26 (BOOO B2); the second apply was a no-op. The manual steps
below are done: the bootstrap role exists, and all five GitHub Environments have their
reviewers, `main`-only deployment branches, and `AWS_ROLE_ARN` secrets. From here, this root
changes only when a role needs a permission (see "After the first apply").

## What each role can do

| Role | Scope |
|---|---|
| bootstrap (manual) | The state bucket, the `loria-dora/*` ECR repositories, the `…-deploy-*` roles and policies, and the task boundary. Nothing that runs anything. |
| `…-deploy-shared` | The VPC, subnets, routes, internet gateway, VPC endpoints and their security group, all tagged `Environment=shared`, `Project=loria-dora`. |
| `…-deploy-<env>` | That environment's security groups, ALB, RDS instance, secrets, SSM parameters, log groups, ECS cluster, service, task definitions and one-off tasks, and its task roles (which must carry the task boundary). Reads the ECR images; **only `deploy-dev` can push them**. |

Each deploy role trusts only its own GitHub Environment:
`repo:loriamichaelj@165821667/dora@1387517226:environment:<env>`.

## One-time manual setup

AWS has to trust GitHub before any workflow can reach it, and a workflow can't
grant itself that trust. These are the only manual AWS/GitHub steps in the project.
Replace `<ACCOUNT_ID>` with your 12-digit account ID throughout.

### 1. GitHub OIDC identity provider: already exists

The account is shared with Beacon, which created
`https://token.actions.githubusercontent.com` (audience `sts.amazonaws.com`). Nothing to do.
Terraform reads the provider but never manages it.

### 2. The bootstrap role (IAM → Roles → Create role)

1. Trusted entity: **Web identity**, choose the GitHub provider, audience `sts.amazonaws.com`.
   Skip the GitHub organization/repository fields; the trust policy is replaced next.
2. Skip attaching permissions. Name the role **`cloudbatch818-loria-dora-bootstrap`** and create it.
3. Open the role → **Trust relationships** → Edit, and paste
   [`manual/bootstrap-role-trust.json`](manual/bootstrap-role-trust.json).
   Only a job running in the `bootstrap` GitHub Environment of this repository can assume it.
4. **Permissions** → Add permissions → Create inline policy → JSON, and paste
   [`manual/bootstrap-role-permissions.json`](manual/bootstrap-role-permissions.json).
   Any policy name works; reusing the role name is simplest.

The name must start with `cloudbatch818-` (an account rule) and must **not** match
`cloudbatch818-loria-dora-deploy-*`. The bootstrap role can only manage roles matching that
pattern, so a name outside it keeps the role from modifying its own permissions. Nothing else
references the name; the workflow only uses the ARN from the `AWS_ROLE_ARN` secret.

The ECR statement names region `us-east-1`; change it if `AWS_REGION` in `project.env` changes.

### 3. The GitHub Environments (repo → Settings → Environments)

| Environment | Required reviewers | Deployment branches | Secret `AWS_ROLE_ARN` |
|---|---|---|---|
| `bootstrap` | yourself | `main` only | `arn:aws:iam::<ACCOUNT_ID>:role/cloudbatch818-loria-dora-bootstrap` |
| `shared` | yourself | `main` only | set after the first apply |
| `dev` | none | `main` only | set after the first apply |
| `stage` | yourself | `main` only | set after the first apply |
| `prod` | yourself (ideally not stage's reviewer) | `main` only | set after the first apply |

"`main` only" matters: every workflow runs from `main`, so a workflow copied onto another
branch can never obtain a role.

## Running it

Actions → **bootstrap** → Run workflow, with `action=plan` first and then `action=apply`.
`ref` selects which branch's `infra/bootstrap` code to run (default `dev`). Each run waits
for your approval in the `bootstrap` Environment.

The workflow:

1. Loads `infra/project.env`, then assumes the bootstrap role via OIDC.
2. Creates the state bucket if it's missing (`scripts/bootstrap/ensure-state-bucket.sh`).
3. Runs `terraform init` against `s3://loria-dora-tfstate-<account-id>/env:/shared/bootstrap.tfstate`.
4. Runs `plan`, then `apply` if requested. The first apply imports the state bucket and
   creates everything else. A second apply should report no changes.
5. Lists the deploy role names in the job summary. It shows names, not ARNs, because the repo is
   public and ARNs contain the account ID.

## After the first apply

Set each Environment's `AWS_ROLE_ARN` secret to `arn:aws:iam::<ACCOUNT_ID>:role/<role>`:

| Environment | Role |
|---|---|
| `shared` | `cloudbatch818-loria-dora-deploy-shared` |
| `dev` | `cloudbatch818-loria-dora-deploy-dev` |
| `stage` | `cloudbatch818-loria-dora-deploy-stage` |
| `prod` | `cloudbatch818-loria-dora-deploy-prod` |

For example: `gh secret set AWS_ROLE_ARN --env dev --body "arn:aws:iam::<ACCOUNT_ID>:role/cloudbatch818-loria-dora-deploy-dev"`.

The bootstrap role is then only needed when this root changes. Examples: adding DNS
permissions to the shared role later (§6.10), or granting a deploy role a missing
permission after an AccessDenied. Change `iam.tf` on `dev`, then run bootstrap `plan` and
`apply` again.

**Never destroy this root.** It holds the state of every other root, every image, and every
role. The state bucket and ECR repositories have `prevent_destroy`, and the bootstrap role
is denied `s3:DeleteBucket`.
