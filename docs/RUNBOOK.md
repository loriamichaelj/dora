# Runbook: Dora on AWS

How to operate Dora on AWS: deploy, roll back, seed, recover from a failed
pipeline, and change infrastructure. The why behind each is in
[`CLOUD-DEVOPS-DESIGN.md`](CLOUD-DEVOPS-DESIGN.md) (§ numbers below refer to it).

Every AWS change runs through GitHub Actions. Nothing here needs AWS credentials on
a laptop. Run workflows from the Actions tab, or with `gh workflow run <file>
--repo loriamichaelj/dora --ref main -f <input>=<value>`; every workflow runs from `main`.

## What's where

| | dev |
|---|---|
| App | http://loria-dora-dev-alb-1183097088.us-east-1.elb.amazonaws.com (HTTP until DNS lands, §6.10) |
| ECS | cluster `loria-dora-dev`, service `loria-dora-dev-app` |
| Database | RDS `loria-dora-dev-db`, PostgreSQL 18 |
| Running release | SSM `/loria-dora/dev/release-version` (its history is the rollback record) |
| Deploy settings | SSM `/loria-dora/dev/deploy-config` ([contract](../deploy/ecs/README.md)) |
| Logs | CloudWatch `/loria-dora/dev/app` (streams `api/…`, `web/…`), `/loria-dora/dev/jobs` (one-off tasks) |
| Images | ECR `loria-dora/api`, `loria-dora/web`, `loria-dora/dbinit`, tagged `<version>` and `sha-<commit>` |
| Releases | GitHub tags `release-<version>`: a pre-release each, created by the first deploy of a release; official releases are promoted by hand (below) |

`/version` on the app, and the footer of every page, show the commit that's running.

## Deploy dev

```sh
gh workflow run deploy.yml --repo loriamichaelj/dora --ref main -f ref=dev
```

`deploy.yml` (§7.2): computes the release version, runs `make ci`, builds and pushes any
image not already in ECR (on an arm64 runner), then preflight → database bootstrap →
migrations → rolling update → release pointer → curl and browser smoke tests. Dev has no
reviewer, so it starts at once. About 15 minutes.

- **Nothing to deploy?** If dev already runs the release, the rollout is skipped (a docs- or
  infra-only commit keeps the same version, §7.1). `-f force=true` replaces the tasks anyway.
- **Self-tracking:** every deploy records itself in dev's own tracker as a `dora-tracker`
  development deployment, best effort (§7.6).
- **GitHub release:** the first deploy of a release tags its commit `release-<version>` and
  publishes a pre-release. To make a deployed release **official**, promote it and add notes
  on what changed:
  ```sh
  gh release edit release-<version> --repo loriamichaelj/dora --prerelease=false --latest --notes-file notes.md
  ```
- **Which commit runs:** the one the release's images were built from. A later commit with
  the same app code (say, a docs change) redeploys those images, so `/version`, the smoke test,
  self-tracking, and the release tag all use the build commit; the job summary shows both.

## Roll back

Use it when a release is bad and fixing forward would take longer than going back. For
the common case, new tasks that never become healthy, you don't need it: the ECS circuit
breaker already rolled back by itself and the deploy failed.

1. **Dry run first.** It checks every rule and changes nothing:
   ```sh
   gh workflow run rollback.yml --repo loriamichaelj/dora --ref main \
     -f environment=dev -f reason="<why>" -f dry_run=true
   ```
2. **Roll back:** the same, with `-f dry_run=false`. By default the target is the release
   that ran before the current one. Or pass `-f target=<version>`, `release-<version>`, or a
   full commit SHA.
3. **Record the failure** that caused it on the Failures page of the app, linked to the bad
   deployment, so the change fail rate and recovery time count it.
4. **Fix forward**, then deploy as usual. Or roll forward to a known-good release with
   `-f target=<version>`.

The rules (§7.5), checked before anything changes:

| Rule | Means | Override |
|---|---|---|
| published | the target's three images are in ECR | none |
| proven | the target has run in this environment before | `allow_unproven` (dev only) |
| schema | if the migrations differ, the target must be the previous release | `allow_schema_change`, only if the older code works with the newer schema |

A rollback registers the target's own task-definition template, never runs migrations,
waits for the service to be stable, moves the release pointer, and runs the target's smoke
tests. It's recorded in dev's tracker as a **remediation** deployment. It shares the deploy
queue, so it never runs alongside a deploy.

## Seed dev

```sh
gh workflow run seed.yml --repo loriamichaelj/dora --ref main
```

Loads 90 days of demo data (`python -m app.seed --days 90 --seed 42`) with the running
release, as a one-off task. Safe to rerun: it replaces only its own demo services and leaves
`dora-tracker` alone. Dev only.

## When a pipeline fails

A failed deploy or rollback opens (or comments on) the issue **`[dev] pipeline failure`**,
assigned to whoever ran it. The next success closes it. Open the run from the issue, find the
failed job, and:

| Where it failed | Likely cause | What to do |
|---|---|---|
| Test / make ci, with `connection reset` or `ImageNotFound` pulling an image | Docker Hub dropped a connection | `gh run rerun <run-id> --failed` (the pre-pull step retries four times first) |
| Test / make ci, a test failure | a real regression | fix it on `dev`; `dev-ci` shows the same failure |
| Preflight: `No parameter …/deploy-config` or `No ECS service` | dev's infrastructure isn't applied | `terraform.yml target=infra environment=dev` (below) |
| Preflight: `has no … image in ECR` | the build didn't finish | rerun the deploy; it builds only what's missing |
| Database bootstrap or Migrate | the task's own error | its CloudWatch log is printed in the step, under "… logs" |
| Roll out: `circuit breaker rolled back` | the new tasks never became healthy | dev is still on the previous release. Read `/loria-dora/dev/app` for the new tasks' errors |
| Smoke test or Browser smoke test | the release is live but broken | roll back (above), then fix forward |
| Anything, with `AccessDenied` | a deploy role lacks a permission | add it to `infra/bootstrap/iam.tf` on `dev`, then bootstrap `plan` and `apply` |

## Change infrastructure

Every Terraform root runs from `main`, with its code from a branch (`ref`, default `dev`).
Plan first; read the plan; then apply.

| Root | Workflow | Runs as | Approval |
|---|---|---|---|
| `infra/bootstrap` | `bootstrap.yml -f action=plan\|apply` | the manual bootstrap role | you, in `bootstrap` |
| `infra/network` | `terraform.yml -f target=network -f action=…` | `deploy-shared` | you, in `shared` |
| `infra/env` | `terraform.yml -f target=infra -f environment=dev -f action=…` | `deploy-dev` | none |

`terraform.yml` refuses to run if the state key, the environment, and the `.tfvars` file
disagree, and fails cleanly for stage and prod, which have no `.tfvars` yet.

**Changing a workflow** (anything in `.github/` on `main`): branch `workflows/<name>` from
`main`, change it, and open a PR into `main`. **Lint workflows** (actionlint) must pass
before it can merge. Keep the branch after merging.

Things to know:

- **The account's VPC quota is full** (5 in us-east-1). A new VPC needs a Service Quotas
  increase first.
- **Secrets never appear in state or logs.** The database passwords are written once from
  ephemeral values (§6.6); rotating them is deferred (§11). Don't recreate the secrets
  without also recreating the database, or the stored passwords won't match the roles.
- **Never destroy `infra/bootstrap`.** It holds every root's state, every image, and every role.

## Cost

Dev costs about $110/month (§9): ~$58 for the VPC endpoints, the rest for the ALB, Fargate,
and RDS. To stop paying for it:

1. `terraform.yml -f target=infra -f environment=dev -f action=destroy` (−~$50).
2. Then, only once no environment is left, `terraform.yml -f target=network -f action=destroy` (−~$58).

Rebuild in the opposite order: network, then infra, then deploy (the service comes up at
zero tasks and the first deploy scales it). The next section is the full drill.

## Tear down and rebuild dev

The procedure for tearing dev down and rebuilding it from code alone (design §10.1).
**Skipped as a Phase B milestone (B8) and never run;** it's here for when it's needed. Before
using it, decide design open items 7–10: the database's data, the network's scope,
self-tracking, and cost reporting.

**Before you start:**

- If dev's data matters (open item 7), save it first: the database is deleted with no snapshot.
- If the network is included (open item 8), make sure there's room for a VPC: the account is at
  its quota of 5 in us-east-1.
- Note the current release: `gh release list --repo loriamichaelj/dora` (the newest is running).

**1. Tear down** (infra first; the network only once no environment uses it):

```sh
gh workflow run terraform.yml --repo loriamichaelj/dora --ref main -f target=infra -f environment=dev -f action=plan
gh workflow run terraform.yml --repo loriamichaelj/dora --ref main -f target=infra -f environment=dev -f action=destroy
gh workflow run terraform.yml --repo loriamichaelj/dora --ref main -f target=network -f action=destroy   # approve in shared
```

Check: each run's summary shows "Plan: 0 to add, 0 to change, N to destroy" and the log ends
with "Destroy complete". The app URL stops answering.

**2. Rebuild:**

```sh
gh workflow run terraform.yml --repo loriamichaelj/dora --ref main -f target=network -f action=apply   # approve in shared
gh workflow run terraform.yml --repo loriamichaelj/dora --ref main -f target=infra -f environment=dev -f action=apply
gh workflow run deploy.yml --repo loriamichaelj/dora --ref main -f ref=dev
```

**3. Check:**

- The deploy's build job says each image **is already in ECR; not rebuilding**, and the
  rollout, smoke tests, and browser smoke tests pass.
- The infra run's `alb_url` output is the new URL: update "What's where" above.
- A second `apply` of the network and of infra each reports **No changes**.
- The app's footer shows the release's commit.

**4. Afterwards:**

- Dev's database is new and empty. Create `dora-tracker` in the UI (unless open item 9 automated
  it), and run `seed.yml` if you want the demo data back.
- The rollback history started over: a rollback to a release from before the drill needs
  `-f allow_unproven=true`.
- Record the teardown and rebuild times and dev's cost (open item 10) in design §10.1.
