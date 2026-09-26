#!/usr/bin/env python3
"""Deploy steps for Dora on ECS (docs/CLOUD-DEVOPS-DESIGN.md §7).

Each subcommand is one step of deploy.yml or rollback.yml. It runs on a GitHub
Actions runner with that environment's deploy role, calls AWS only through the
AWS CLI, writes results to stdout (JSON where structured) and progress to
stderr. Standard library only, Python 3.10+ (D58), like record_deploy.py.

    ecs_deploy.py version                              release version of HEAD (§7.1)
    ecs_deploy.py preflight --version V                infra and images exist (§7.4)
    ecs_deploy.py register --family F --release R.json render and register a task definition
    ecs_deploy.py run-task --task-definition ARN       one-off task to completion (§7.3)
    ecs_deploy.py rollout --task-definition ARN        update the service, wait until stable
    ecs_deploy.py publish --version V                  write the release-version pointer
    ecs_deploy.py resolve-rollback --reason ...        pick and check a rollback target (§7.5)

Requires NAME_PREFIX and AWS_REGION (infra/project.env) and ENVIRONMENT.
Exit codes: 0 success, 1 a check or AWS call failed, 2 bad usage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import string
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = REPO_ROOT / "deploy" / "ecs"

ENVIRONMENTS = ("dev", "stage", "prod")
FAMILIES = ("app", "migrate", "db-bootstrap", "seed")
IMAGES = ("api", "web", "dbinit")
# The trees a release is built from (§7.1): the api, web, and dbinit images.
RELEASE_TREES = ("api", "web", "db")
MIGRATIONS = "api/alembic/versions"

VERSION_RE = re.compile(r"^[0-9a-f]{12}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
NO_RELEASE = "none"  # release-version's value until the first deploy (§7.4)

# What infra/env publishes as /<name_prefix>/<env>/deploy-config (§6.8).
# See deploy/ecs/README.md for each key.
CONFIG_KEYS = (
    "cluster",
    "service",
    "subnets",
    "security_group",
    "desired_count",
    "cpu",
    "memory",
    "task_role_arn",
    "execution_role_arn",
    "db_bootstrap_execution_role_arn",
    "app_log_group",
    "jobs_log_group",
    "db_host",
    "db_port",
    "db_name",
    "db_master_secret_arn",
    "db_owner_secret_arn",
    "db_app_secret_arn",
    "ingest_api_key_secret_arn",
    "alb_dns_name",
)


class DeployError(Exception):
    """A failed check or step, with a message meant for the job log."""


class AwsError(DeployError):
    def __init__(self, args: list[str], stderr: str) -> None:
        self.code = _error_code(stderr)
        super().__init__(f"aws {' '.join(args[:2])} failed: {stderr.strip() or 'no output'}")


def _error_code(stderr: str) -> str:
    match = re.search(r"An error occurred \((\w+)\)", stderr)
    return match.group(1) if match else ""


def log(message: str) -> None:
    print(f"ecs_deploy: {message}", file=sys.stderr, flush=True)


# ---- the AWS CLI boundary ------------------------------------------------------

Runner = Callable[[list[str]], str]


def run_aws(args: list[str]) -> str:
    """Run `aws <args>`; the one place this module touches AWS (tests replace it)."""
    proc = subprocess.run(["aws", *args], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise AwsError(args, proc.stderr)
    return proc.stdout


class Aws:
    def __init__(self, region: str, runner: Runner = run_aws) -> None:
        self.region = region
        self.runner = runner

    def __call__(self, *args: str) -> Any:
        out = self.runner([*args, "--region", self.region, "--output", "json"])
        return json.loads(out) if out.strip() else None


@dataclass(frozen=True)
class Context:
    name_prefix: str
    environment: str
    region: str

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> Context:
        missing = [k for k in ("NAME_PREFIX", "AWS_REGION", "ENVIRONMENT") if not environ.get(k)]
        if missing:
            raise DeployError(f"missing environment variables: {', '.join(missing)}")
        environment = environ["ENVIRONMENT"]
        if environment not in ENVIRONMENTS:
            raise DeployError(f"ENVIRONMENT must be dev, stage, or prod (got {environment!r})")
        return cls(environ["NAME_PREFIX"], environment, environ["AWS_REGION"])

    def parameter(self, name: str, environment: str | None = None) -> str:
        return f"/{self.name_prefix}/{environment or self.environment}/{name}"

    def repository(self, image: str) -> str:
        return f"{self.name_prefix}/{image}"


# ---- release version (§7.1) ----------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def release_version(repo: Path = REPO_ROOT, rev: str = "HEAD") -> str:
    """Hash of the api/, web/, and db/ trees: survives promotion merges, and
    docs- or infra-only changes keep the same version. Equivalent to
    printf '%s %s %s' <tree ids> | sha256sum | cut -c1-12."""
    trees = [_git(repo, "rev-parse", f"{rev}:{tree}") for tree in RELEASE_TREES]
    return hashlib.sha256(" ".join(trees).encode()).hexdigest()[:12]


# ---- reads ---------------------------------------------------------------------


def read_parameter(aws: Aws, name: str) -> str | None:
    try:
        return aws("ssm", "get-parameter", "--name", name)["Parameter"]["Value"]
    except AwsError as exc:
        if exc.code == "ParameterNotFound":
            return None
        raise


def read_deploy_config(aws: Aws, ctx: Context) -> dict[str, Any]:
    name = ctx.parameter("deploy-config")
    raw = read_parameter(aws, name)
    if raw is None:
        raise DeployError(
            f"No parameter {name}. Has terraform.yml target=infra been applied "
            f"for {ctx.environment}?"
        )
    config = json.loads(raw)
    missing = [k for k in CONFIG_KEYS if k not in config]
    if missing:
        raise DeployError(f"{name} is missing keys: {', '.join(missing)}")
    return config


def find_image(aws: Aws, ctx: Context, image: str, tag: str) -> dict[str, Any] | None:
    """The ECR image tagged `tag`, or None."""
    try:
        details = aws(
            "ecr",
            "describe-images",
            "--repository-name",
            ctx.repository(image),
            "--image-ids",
            f"imageTag={tag}",
        )["imageDetails"]
    except AwsError as exc:
        if exc.code == "ImageNotFoundException":
            return None
        raise
    return details[0] if details else None


def image_uri(ctx: Context, image: str, detail: Mapping[str, Any]) -> str:
    registry = f"{detail['registryId']}.dkr.ecr.{ctx.region}.amazonaws.com"
    return f"{registry}/{ctx.repository(image)}@{detail['imageDigest']}"


def release_images(aws: Aws, ctx: Context, version: str) -> tuple[dict[str, str], list[str]]:
    """Digest URIs of the release's images, and the names of any missing."""
    found, missing = {}, []
    for image in IMAGES:
        detail = find_image(aws, ctx, image, version)
        if detail is None:
            missing.append(image)
        else:
            found[image] = image_uri(ctx, image, detail)
    return found, missing


def release_commit(aws: Aws, ctx: Context, version: str) -> str | None:
    """The commit a release was built from: its images' sha-<commit> tag."""
    detail = find_image(aws, ctx, "api", version)
    for tag in (detail or {}).get("imageTags", []):
        if tag.startswith("sha-") and SHA_RE.match(tag[4:]):
            return tag[4:]
    return None


# ---- preflight (§7.2 step 4, §7.4) ---------------------------------------------


def preflight(aws: Aws, ctx: Context, version: str) -> dict[str, Any]:
    if not VERSION_RE.match(version):
        raise DeployError(f"not a release version: {version!r}")
    config = read_deploy_config(aws, ctx)

    clusters = aws("ecs", "describe-clusters", "--clusters", config["cluster"])["clusters"]
    if not clusters or clusters[0]["status"] != "ACTIVE":
        raise DeployError(f"No active ECS cluster {config['cluster']}.")
    services = aws(
        "ecs", "describe-services", "--cluster", config["cluster"], "--services", config["service"]
    )["services"]
    if not services or services[0]["status"] != "ACTIVE":
        raise DeployError(
            f"No ECS service {config['service']}. Has terraform.yml target=infra been "
            f"applied for {ctx.environment}?"
        )

    images, missing = release_images(aws, ctx, version)
    if missing:
        if ctx.environment == "stage":
            raise DeployError(f"Release {version} was never deployed to dev: no image in ECR.")
        raise DeployError(f"Release {version} has no {', '.join(missing)} image in ECR.")

    # Only exactly what stage runs may reach prod (§7.2 step 4).
    if ctx.environment == "prod":
        staged = read_parameter(aws, ctx.parameter("release-version", "stage"))
        if staged != version:
            raise DeployError(f"Release {version} isn't what stage runs ({staged or 'nothing'}).")

    log(f"preflight passed for {version} in {ctx.environment}")
    return {"version": version, "images": images}


# ---- task definitions ------------------------------------------------------------


def render(
    ctx: Context, family: str, config: Mapping[str, Any], release: Mapping[str, Any]
) -> dict[str, Any]:
    """deploy/ecs/<family>.json.tmpl with this environment's values."""
    if family not in FAMILIES:
        raise DeployError(f"unknown task family {family!r}")
    values = {key.upper(): str(config[key]) for key in CONFIG_KEYS if key in config}
    values.update(
        NAME_PREFIX=ctx.name_prefix,
        ENVIRONMENT=ctx.environment,
        AWS_REGION=ctx.region,
        RELEASE_VERSION=release["version"],
        **{f"{image.upper()}_IMAGE": uri for image, uri in release["images"].items()},
    )
    # Values go inside JSON strings, so escape them as such.
    escaped = {k: json.dumps(v)[1:-1] for k, v in values.items()}
    template = string.Template((TEMPLATES / f"{family}.json.tmpl").read_text())
    try:
        rendered = json.loads(template.substitute(escaped))
    except KeyError as exc:
        raise DeployError(f"{family}.json.tmpl needs {exc.args[0]}, which isn't set") from exc
    return rendered


def register(
    aws: Aws, ctx: Context, family: str, config: Mapping[str, Any], release: Mapping[str, Any]
) -> str:
    definition = render(ctx, family, config, release)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(definition, fh)
    try:
        result = aws("ecs", "register-task-definition", "--cli-input-json", f"file://{fh.name}")
    finally:
        os.unlink(fh.name)
    arn = result["taskDefinition"]["taskDefinitionArn"]
    log(f"registered {arn}")
    return arn


# ---- one-off tasks (§7.3) --------------------------------------------------------


def run_task(
    aws: Aws, config: Mapping[str, Any], task_definition: str, started_by: str = "ecs_deploy"
) -> None:
    """Run a one-off task to completion; print its logs; fail unless it exited 0."""
    network = {
        "awsvpcConfiguration": {
            "subnets": config["subnets"],
            "securityGroups": [config["security_group"]],
            "assignPublicIp": "DISABLED",
        }
    }
    started = aws(
        "ecs",
        "run-task",
        "--cluster",
        config["cluster"],
        "--task-definition",
        task_definition,
        "--launch-type",
        "FARGATE",
        "--network-configuration",
        json.dumps(network),
        "--propagate-tags",
        "TASK_DEFINITION",
        "--started-by",
        started_by[:36],
    )
    if started.get("failures"):
        raise DeployError(f"run-task failed: {started['failures']}")
    task_arn = started["tasks"][0]["taskArn"]
    log(f"started {task_arn}; waiting for it to stop")
    try:
        aws("ecs", "wait", "tasks-stopped", "--cluster", config["cluster"], "--tasks", task_arn)
    except AwsError as exc:
        raise DeployError(f"task {task_arn} didn't stop in time: {exc}") from exc

    task = aws("ecs", "describe-tasks", "--cluster", config["cluster"], "--tasks", task_arn)[
        "tasks"
    ][0]
    container = task["containers"][0]
    print_task_logs(aws, config["jobs_log_group"], container["name"], task_arn)
    exit_code = container.get("exitCode")
    if exit_code != 0:
        reason = container.get("reason") or task.get("stoppedReason") or "no reason given"
        raise DeployError(f"{container['name']} exited with {exit_code}: {reason}")
    log(f"{container['name']} succeeded")


def print_task_logs(aws: Aws, group: str, container: str, task_arn: str) -> None:
    """Copy the task's log stream into the job log (stream prefix = container name)."""
    stream = f"{container}/{container}/{task_arn.rsplit('/', 1)[-1]}"
    try:
        events = aws(
            "logs",
            "get-log-events",
            "--log-group-name",
            group,
            "--log-stream-name",
            stream,
            "--start-from-head",
        )["events"]
    except AwsError as exc:
        log(f"no logs from {group}:{stream} ({exc.code or exc})")
        return
    print(f"::group::{container} logs", file=sys.stderr)
    for event in events:
        print(event["message"], file=sys.stderr)
    print("::endgroup::", file=sys.stderr, flush=True)


# ---- rollout and the release pointer (§7.2 steps 8-9) -----------------------------


def rollout(aws: Aws, config: Mapping[str, Any], task_definition: str) -> None:
    cluster, service = config["cluster"], config["service"]
    current = aws("ecs", "describe-services", "--cluster", cluster, "--services", service)[
        "services"
    ][0]
    args = ["--task-definition", task_definition]
    # Terraform creates the service with 0 tasks; the first deploy scales it (§7.4).
    if current["desiredCount"] == 0:
        args += ["--desired-count", str(config["desired_count"])]
    aws("ecs", "update-service", "--cluster", cluster, "--service", service, *args)
    log(f"updated {service}; waiting for it to be stable")
    try:
        aws("ecs", "wait", "services-stable", "--cluster", cluster, "--services", service)
    except AwsError as exc:
        raise DeployError(f"{service} didn't become stable: {exc}") from exc

    # The circuit breaker may have rolled back to the previous revision, which
    # also leaves the service stable: check which revision is actually live.
    after = aws("ecs", "describe-services", "--cluster", cluster, "--services", service)[
        "services"
    ][0]
    primary = next(d for d in after["deployments"] if d["status"] == "PRIMARY")
    if primary["taskDefinition"] != task_definition or primary.get("rolloutState") != "COMPLETED":
        raise DeployError(
            f"{service} is running {primary['taskDefinition']} "
            f"({primary.get('rolloutState', 'unknown')}), not {task_definition}: the new "
            "tasks never became healthy and the circuit breaker rolled back."
        )
    log(f"{service} is running {task_definition}")


def publish(aws: Aws, ctx: Context, version: str) -> None:
    name = ctx.parameter("release-version")
    aws("ssm", "put-parameter", "--name", name, "--value", version, "--overwrite")
    log(f"{name} = {version}")


# ---- rollback rules (§7.5) --------------------------------------------------------


def release_history(aws: Aws, ctx: Context) -> list[str]:
    """Every release this environment has run, oldest first."""
    history = aws("ssm", "get-parameter-history", "--name", ctx.parameter("release-version"))
    values = [p["Value"] for p in history["Parameters"]]
    return [v for v in values if v != NO_RELEASE]


def resolve_target(aws: Aws, ctx: Context, target: str, current: str, history: list[str]) -> str:
    if target == "previous":
        earlier = [v for v in history if v != current]
        if not earlier:
            raise DeployError(f"{ctx.environment} has no earlier release to roll back to.")
        return earlier[-1]
    if VERSION_RE.match(target):
        return target
    if SHA_RE.match(target):
        detail = find_image(aws, ctx, "api", f"sha-{target}")
        versions = [t for t in (detail or {}).get("imageTags", []) if VERSION_RE.match(t)]
        if not versions:
            raise DeployError(f"No release was built from commit {target}.")
        return versions[0]
    raise DeployError(
        f"--target must be 'previous', a 12-character release version, or a full "
        f"40-character commit SHA (got {target!r})."
    )


def schema_changed(repo: Path, a: str, b: str) -> bool:
    """Whether the migrations differ between two commits (needs both fetched)."""
    proc = subprocess.run(
        ["git", "-C", str(repo), "diff", "--quiet", a, b, "--", MIGRATIONS],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode not in (0, 1):
        raise DeployError(f"can't compare migrations of {a} and {b}: {proc.stderr.strip()}")
    return proc.returncode == 1


def resolve_rollback(
    aws: Aws,
    ctx: Context,
    *,
    target: str,
    reason: str,
    allow_schema_change: bool = False,
    allow_unproven: bool = False,
    repo: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Pick the rollback target and check every rule before anything changes."""
    if not reason.strip():
        raise DeployError("A rollback needs a reason.")
    if allow_unproven and ctx.environment != "dev":
        raise DeployError("Only dev may roll back to a release it never ran.")

    current = read_parameter(aws, ctx.parameter("release-version"))
    if not current or current == NO_RELEASE:
        raise DeployError(f"{ctx.environment} has never been deployed; nothing to roll back.")
    history = release_history(aws, ctx)
    version = resolve_target(aws, ctx, target, current, history)
    if version == current:
        raise DeployError(f"{ctx.environment} is already running {version}.")

    # published: its images are in ECR.
    images, missing = release_images(aws, ctx, version)
    if missing:
        raise DeployError(f"Release {version} has no {', '.join(missing)} image in ECR.")

    # proven: it has run here before.
    if version not in history and not allow_unproven:
        raise DeployError(f"Release {version} has never run in {ctx.environment}.")

    # schema: rolling back across a migration is only safe to the release just
    # before, whose code the expand-then-contract rule keeps compatible (§7.3).
    previous = next((v for v in reversed(history) if v != current), None)
    commits = {v: release_commit(aws, ctx, v) for v in (current, version)}
    if None in commits.values():
        raise DeployError("Can't find the commits of both releases (no sha-<commit> image tag).")
    if (
        version != previous
        and schema_changed(repo, commits[current], commits[version])
        and not allow_schema_change
    ):
        raise DeployError(
            f"Migrations differ between {current} and {version}, which isn't the previous "
            "release. Set allow_schema_change if the older code works with the newer schema."
        )

    log(f"rollback {ctx.environment}: {current} -> {version} ({reason.strip()})")
    return {"version": version, "images": images, "from": current, "commit": commits[version]}


# ---- CLI -------------------------------------------------------------------------


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("version", help="print the release version of HEAD")

    p = sub.add_parser("preflight", help="check infra and images; print the release JSON")
    p.add_argument("--version", required=True)

    p = sub.add_parser("register", help="render and register a task definition; print its ARN")
    p.add_argument("--family", required=True, choices=FAMILIES)
    p.add_argument("--release", required=True, type=Path, help="JSON from preflight")

    p = sub.add_parser("run-task", help="run a one-off task to completion")
    p.add_argument("--task-definition", required=True)
    p.add_argument("--started-by", default=os.environ.get("GITHUB_RUN_ID", "ecs_deploy"))

    p = sub.add_parser("rollout", help="point the service at a task definition and wait")
    p.add_argument("--task-definition", required=True)

    p = sub.add_parser("publish", help="write the release-version pointer")
    p.add_argument("--version", required=True)

    p = sub.add_parser("resolve-rollback", help="check a rollback; print the release JSON")
    p.add_argument("--target", default="previous")
    p.add_argument("--reason", required=True)
    p.add_argument("--allow-schema-change", action="store_true")
    p.add_argument("--allow-unproven", action="store_true", help="dev only")
    return parser.parse_args(argv)


def run(args: argparse.Namespace, environ: Mapping[str, str], runner: Runner) -> Any:
    if args.command == "version":
        return release_version()
    ctx = Context.from_env(environ)
    aws = Aws(ctx.region, runner)
    if args.command == "preflight":
        return preflight(aws, ctx, args.version)
    if args.command == "resolve-rollback":
        return resolve_rollback(
            aws,
            ctx,
            target=args.target,
            reason=args.reason,
            allow_schema_change=args.allow_schema_change,
            allow_unproven=args.allow_unproven,
        )
    if args.command == "publish":
        publish(aws, ctx, args.version)
        return None
    config = read_deploy_config(aws, ctx)
    if args.command == "register":
        release = json.loads(args.release.read_text())
        return register(aws, ctx, args.family, config, release)
    if args.command == "run-task":
        run_task(aws, config, args.task_definition, args.started_by)
        return None
    rollout(aws, config, args.task_definition)
    return None


def main(
    argv: list[str] | None = None,
    environ: Mapping[str, str] | None = None,
    runner: Runner = run_aws,
) -> int:
    args = parse_args(argv)
    try:
        result = run(args, os.environ if environ is None else environ, runner)
    except DeployError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return EXIT_FAILED
    if result is not None:
        print(result if isinstance(result, str) else json.dumps(result, indent=2))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
