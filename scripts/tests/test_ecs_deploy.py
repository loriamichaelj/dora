"""scripts/deploy/ecs_deploy.py against a stubbed AWS CLI (cloud design §7, §8)."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from conftest import Repo

import ecs_deploy as ed

REGION = "us-east-1"
ACCOUNT = "123456789012"
PREFIX = "loria-dora"
V1, V2, V3 = "aaaaaaaaaaa1", "bbbbbbbbbbb2", "ccccccccccc3"
SHA1, SHA2, SHA3 = "1" * 40, "2" * 40, "3" * 40
REPO_ROOT = Path(__file__).resolve().parents[2]


def arn(service: str, resource: str) -> str:
    return f"arn:aws:{service}:{REGION}:{ACCOUNT}:{resource}"


def deploy_config(env: str = "dev") -> dict[str, Any]:
    base = f"{PREFIX}-{env}"
    return {
        "cluster": base,
        "service": f"{base}-app",
        "subnets": ["subnet-aaa", "subnet-bbb"],
        "security_group": "sg-123",
        "desired_count": 1,
        "cpu": "512",
        "memory": "1024",
        "task_role_arn": f"arn:aws:iam::{ACCOUNT}:role/cloudbatch818-{base}-task",
        "execution_role_arn": f"arn:aws:iam::{ACCOUNT}:role/cloudbatch818-{base}-task-exec",
        "db_bootstrap_execution_role_arn": (
            f"arn:aws:iam::{ACCOUNT}:role/cloudbatch818-{base}-db-bootstrap-exec"
        ),
        "app_log_group": f"/{PREFIX}/{env}/app",
        "jobs_log_group": f"/{PREFIX}/{env}/jobs",
        "db_host": f"{base}-db.abc.{REGION}.rds.amazonaws.com",
        "db_port": 5432,
        "db_name": "dora",
        "db_master_secret_arn": arn("secretsmanager", "secret:rds!db-1234-AbCdEf"),
        "db_owner_secret_arn": arn("secretsmanager", f"secret:{PREFIX}/{env}/db-owner-AbCdEf"),
        "db_app_secret_arn": arn("secretsmanager", f"secret:{PREFIX}/{env}/db-app-AbCdEf"),
        "ingest_api_key_secret_arn": arn(
            "secretsmanager", f"secret:{PREFIX}/{env}/ingest-api-key-AbCdEf"
        ),
        "alb_dns_name": f"{base}-alb-1.{REGION}.elb.amazonaws.com",
    }


def digest(image: str, version: str) -> str:
    return "sha256:" + f"{image}{version}".encode().hex().ljust(64, "0")[:64]


@dataclass
class FakeAws:
    """Just enough AWS for ecs_deploy: SSM parameters (with history), one cluster
    and service per environment, ECR images by tag, one-off tasks, and logs."""

    params: dict[str, list[str]] = field(default_factory=dict)
    clusters: dict[str, str] = field(default_factory=dict)
    services: dict[str, dict[str, Any]] = field(default_factory=dict)
    images: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    task_exit_code: int | None = 0
    task_reason: str | None = None
    unhealthy_rollout: bool = False
    # Describes after the update that still report IN_PROGRESS, then the final state.
    rollout_in_progress_for: int = 0
    rollout_final_state: str = "COMPLETED"
    registered: list[dict[str, Any]] = field(default_factory=list)
    calls: list[list[str]] = field(default_factory=list)
    log_events: list[str] = field(default_factory=lambda: ["INFO upgrade done"])

    # ---- setup helpers ----

    def environment(self, env: str, release: str | None = None) -> None:
        config = deploy_config(env)
        self.params[f"/{PREFIX}/{env}/deploy-config"] = [json.dumps(config)]
        self.params[f"/{PREFIX}/{env}/release-version"] = ["none"] + ([release] if release else [])
        self.clusters[config["cluster"]] = "ACTIVE"
        self.services[config["service"]] = {
            "serviceName": config["service"],
            "status": "ACTIVE",
            "desiredCount": 0,
            "taskDefinition": arn("ecs", f"task-definition/{PREFIX}-{env}-app:1"),
            "deployments": [],
        }

    def release(self, version: str, sha: str, images: tuple[str, ...] = ed.IMAGES) -> None:
        for image in images:
            self.images.setdefault(f"{PREFIX}/{image}", []).append(
                {
                    "registryId": ACCOUNT,
                    "imageDigest": digest(image, version),
                    "imageTags": [version, f"sha-{sha}"],
                }
            )

    def history(self, env: str, *versions: str) -> None:
        self.params[f"/{PREFIX}/{env}/release-version"] = ["none", *versions]

    # ---- the CLI ----

    def __call__(self, argv: list[str]) -> str:
        self.calls.append(argv)
        assert argv[-4:] == ["--region", REGION, "--output", "json"], argv
        service, op, *rest = argv[:-4]
        positional, opts = [], {}
        i = 0
        while i < len(rest):
            if rest[i].startswith("--"):
                has_value = i + 1 < len(rest) and not rest[i + 1].startswith("--")
                opts[rest[i][2:]] = rest[i + 1] if has_value else True
                i += 2 if has_value else 1
            else:
                positional.append(rest[i])
                i += 1
        handler = getattr(self, f"{service}_{op}".replace("-", "_"), None)
        if handler is None:
            raise AssertionError(f"unexpected aws call: {argv}")
        result = handler(argv, positional, opts)
        return "" if result is None else json.dumps(result)

    @staticmethod
    def fail(argv: list[str], code: str) -> None:
        raise ed.AwsError(argv, f"An error occurred ({code}) when calling the operation: nope")

    def ssm_get_parameter(self, argv, _pos, opts):
        values = self.params.get(opts["name"])
        if not values:
            self.fail(argv, "ParameterNotFound")
        return {"Parameter": {"Name": opts["name"], "Value": values[-1]}}

    def ssm_get_parameter_history(self, argv, _pos, opts):
        values = self.params.get(opts["name"])
        if not values:
            self.fail(argv, "ParameterNotFound")
        return {"Parameters": [{"Value": v, "Version": i + 1} for i, v in enumerate(values)]}

    def ssm_put_parameter(self, _argv, _pos, opts):
        assert opts.get("overwrite") is True
        self.params.setdefault(opts["name"], []).append(opts["value"])
        return {"Version": len(self.params[opts["name"]])}

    def ecs_describe_clusters(self, _argv, _pos, opts):
        name = opts["clusters"]
        status = self.clusters.get(name)
        return {"clusters": [{"clusterName": name, "status": status}] if status else []}

    def ecs_describe_services(self, _argv, _pos, opts):
        svc = self.services.get(opts["services"])
        if svc and svc["deployments"]:
            primary = svc["deployments"][0]
            if self.rollout_in_progress_for > 0:
                self.rollout_in_progress_for -= 1
                primary["rolloutState"] = "IN_PROGRESS"
            else:
                primary["rolloutState"] = self.rollout_final_state
                if self.rollout_final_state == "FAILED":
                    primary["rolloutStateReason"] = "ECS deployment circuit breaker: tasks failed"
        return {"services": [svc] if svc else []}

    def ecr_describe_images(self, argv, _pos, opts):
        tag = opts["image-ids"].removeprefix("imageTag=")
        for detail in self.images.get(opts["repository-name"], []):
            if tag in detail["imageTags"]:
                return {"imageDetails": [detail]}
        self.fail(argv, "ImageNotFoundException")

    def ecs_register_task_definition(self, _argv, _pos, opts):
        path = opts["cli-input-json"].removeprefix("file://")
        definition = json.loads(Path(path).read_text())
        self.registered.append(definition)
        revision = sum(d["family"] == definition["family"] for d in self.registered)
        family_arn = arn("ecs", f"task-definition/{definition['family']}:{revision}")
        return {"taskDefinition": {"taskDefinitionArn": family_arn}}

    def ecs_run_task(self, _argv, _pos, opts):
        cluster = opts["cluster"]
        return {
            "tasks": [{"taskArn": arn("ecs", f"task/{cluster}/0123456789abcdef")}],
            "failures": [],
        }

    def ecs_wait(self, argv, pos, _opts):
        if pos == ["services-stable"] and self.unhealthy_rollout:
            return None  # the circuit breaker rolled back: stable, on the old revision
        assert pos in (["tasks-stopped"], ["services-stable"]), argv
        return None

    def ecs_describe_tasks(self, _argv, _pos, opts):
        task_def = next(c for c in reversed(self.calls) if c[1] == "run-task")
        name = task_def[task_def.index("--task-definition") + 1].split("/")[-1].split(":")[0]
        container = name.removeprefix(f"{PREFIX}-dev-")
        return {
            "tasks": [
                {
                    "taskArn": opts["tasks"],
                    "stoppedReason": "Essential container in task exited",
                    "containers": [
                        {
                            "name": container,
                            "exitCode": self.task_exit_code,
                            "reason": self.task_reason,
                        }
                    ],
                }
            ]
        }

    def logs_get_log_events(self, argv, _pos, _opts):
        if not self.log_events:
            self.fail(argv, "ResourceNotFoundException")
        return {"events": [{"message": m} for m in self.log_events]}

    def ecs_update_service(self, _argv, _pos, opts):
        svc = self.services[opts["service"]]
        if "desired-count" in opts:
            svc["desiredCount"] = int(opts["desired-count"])
        new = opts["task-definition"]
        live = svc["taskDefinition"] if self.unhealthy_rollout else new
        svc["taskDefinition"] = live
        svc["deployments"] = [
            {"status": "PRIMARY", "taskDefinition": live, "rolloutState": "COMPLETED"}
        ]
        return {"service": svc}


@pytest.fixture
def fake() -> FakeAws:
    f = FakeAws()
    f.environment("dev")
    return f


def ctx(env: str = "dev") -> ed.Context:
    return ed.Context(PREFIX, env, REGION)


def aws(fake: FakeAws) -> ed.Aws:
    return ed.Aws(REGION, fake)


def ops(fake: FakeAws) -> list[str]:
    return [f"{c[0]} {c[1]}" for c in fake.calls]


# ---- context and the release version ----


def test_context_needs_every_variable_and_a_known_environment() -> None:
    with pytest.raises(ed.DeployError, match="NAME_PREFIX, ENVIRONMENT"):
        ed.Context.from_env({"AWS_REGION": REGION})
    with pytest.raises(ed.DeployError, match="dev, stage, or prod"):
        ed.Context.from_env({"NAME_PREFIX": PREFIX, "AWS_REGION": REGION, "ENVIRONMENT": "qa"})
    c = ed.Context.from_env({"NAME_PREFIX": PREFIX, "AWS_REGION": REGION, "ENVIRONMENT": "dev"})
    assert c.parameter("release-version") == "/loria-dora/dev/release-version"
    assert c.parameter("release-version", "stage") == "/loria-dora/stage/release-version"


def write(repo: Repo, path: str, content: str, message: str) -> str:
    target = repo.path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    repo.git("add", path)
    repo.git("commit", "-q", "-m", message)
    return repo.head()


@pytest.fixture
def app_repo(repo: Repo) -> Repo:
    for tree in ed.RELEASE_TREES:
        write(repo, f"{tree}/README", tree, f"add {tree}")
    return repo


def test_release_version_hashes_the_three_trees(app_repo: Repo) -> None:
    version = ed.release_version(app_repo.path)
    assert re.fullmatch(r"[0-9a-f]{12}", version)
    trees = " ".join(app_repo.git("rev-parse", f"HEAD:{t}") for t in ed.RELEASE_TREES)
    assert version == ed.hashlib.sha256(trees.encode()).hexdigest()[:12]


def test_docs_and_infra_changes_keep_the_version_app_changes_dont(app_repo: Repo) -> None:
    before = ed.release_version(app_repo.path)
    write(app_repo, "docs/x.md", "doc", "docs")
    write(app_repo, "infra/x.tf", "tf", "infra")
    assert ed.release_version(app_repo.path) == before
    write(app_repo, "db/bootstrap.sql", "select 1;", "db change")
    assert ed.release_version(app_repo.path) != before


def test_version_command_prints_this_repos_release_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert ed.main(["version"], environ={}) == 0
    assert capsys.readouterr().out.strip() == ed.release_version(REPO_ROOT)


# ---- preflight ----


def test_preflight_returns_the_release_images_by_digest(fake: FakeAws) -> None:
    fake.release(V1, SHA1)
    result = ed.preflight(aws(fake), ctx(), V1)
    assert result["version"] == V1
    assert result["commit"] == SHA1  # the build commit, from the sha-<commit> tag
    assert result["images"]["api"] == (
        f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/{PREFIX}/api@{digest('api', V1)}"
    )
    assert set(result["images"]) == {"api", "web", "dbinit"}


def test_preflight_explains_missing_infrastructure() -> None:
    fake = FakeAws()
    with pytest.raises(ed.DeployError, match=r"terraform\.yml target=infra been applied for dev"):
        ed.preflight(aws(fake), ctx(), V1)

    fake.environment("dev")
    fake.clusters.clear()
    with pytest.raises(ed.DeployError, match="No active ECS cluster loria-dora-dev"):
        ed.preflight(aws(fake), ctx(), V1)

    fake.environment("dev")
    fake.services.clear()
    with pytest.raises(ed.DeployError, match="No ECS service loria-dora-dev-app"):
        ed.preflight(aws(fake), ctx(), V1)


def test_preflight_names_missing_images(fake: FakeAws) -> None:
    fake.release(V1, SHA1, images=("api", "web"))
    with pytest.raises(ed.DeployError, match="Release aaaaaaaaaaa1 has no dbinit image"):
        ed.preflight(aws(fake), ctx(), V1)


def test_stage_preflight_says_never_deployed_to_dev(fake: FakeAws) -> None:
    fake.environment("stage")
    with pytest.raises(ed.DeployError, match="never deployed to dev"):
        ed.preflight(aws(fake), ctx("stage"), V1)


def test_prod_only_takes_exactly_what_stage_runs(fake: FakeAws) -> None:
    fake.environment("stage", release=V1)
    fake.environment("prod")
    fake.release(V1, SHA1)
    fake.release(V2, SHA2)
    with pytest.raises(ed.DeployError, match="isn't what stage runs"):
        ed.preflight(aws(fake), ctx("prod"), V2)
    assert ed.preflight(aws(fake), ctx("prod"), V1)["version"] == V1


def test_preflight_rejects_a_malformed_version(fake: FakeAws) -> None:
    with pytest.raises(ed.DeployError, match="not a release version"):
        ed.preflight(aws(fake), ctx(), "latest")
    assert fake.calls == []


# ---- task definitions ----


def release(version: str = V1) -> dict[str, Any]:
    return {
        "version": version,
        "images": {i: f"{ACCOUNT}.dkr.ecr/{PREFIX}/{i}@{digest(i, version)}" for i in ed.IMAGES},
    }


def env_of(container: dict[str, Any]) -> dict[str, str]:
    return {e["name"]: e["value"] for e in container.get("environment", [])}


def secrets_of(container: dict[str, Any]) -> dict[str, str]:
    return {s["name"]: s["valueFrom"] for s in container.get("secrets", [])}


@pytest.mark.parametrize("family", ed.FAMILIES)
def test_every_template_renders_a_tagged_arm64_fargate_task(family: str) -> None:
    config = deploy_config()
    td = ed.render(ctx(), family, config, release())
    assert td["family"] == f"loria-dora-dev-{family}"
    assert td["requiresCompatibilities"] == ["FARGATE"]
    assert td["networkMode"] == "awsvpc"
    assert td["runtimePlatform"]["cpuArchitecture"] == "ARM64"
    # The deploy role may only register task definitions carrying both tags (B2).
    tags = {t["key"]: t["value"] for t in td["tags"]}
    assert tags["Project"] == "loria-dora"
    assert tags["Environment"] == "dev"
    assert tags["Release"] == V1
    for container in td["containerDefinitions"]:
        assert "@sha256:" in container["image"]  # by digest, never by tag
        logs = container["logConfiguration"]
        assert logs["logDriver"] == "awslogs"
        # run-task finds a task's stream as <prefix>/<container>/<task id>.
        assert logs["options"]["awslogs-stream-prefix"] == container["name"]
    assert "$" not in json.dumps(td)


def test_app_task_runs_web_in_front_of_a_healthy_api() -> None:
    config = deploy_config()
    td = ed.render(ctx(), "app", config, release())
    api, web = td["containerDefinitions"]
    assert (api["name"], web["name"]) == ("api", "web")
    assert web["dependsOn"] == [{"containerName": "api", "condition": "HEALTHY"}]
    assert web["portMappings"] == [{"containerPort": 8080, "protocol": "tcp"}]
    assert "portMappings" not in api  # only web is reachable from the ALB (§6.3)
    assert env_of(web)["API_UPSTREAM"] == "127.0.0.1:8000"
    assert "/healthz" in " ".join(api["healthCheck"]["command"])  # liveness, not /readyz (C5)
    env = env_of(api)
    assert env["DB_USER"] == "dora_app"
    assert env["DB_SSL_MODE"] == "verify-full"
    assert env["APP_ENV"] == "dev"
    assert (td["cpu"], td["memory"]) == ("512", "1024")
    assert secrets_of(api) == {
        "DB_PASSWORD": config["db_app_secret_arn"] + ":password::",
        "INGEST_API_KEY": config["ingest_api_key_secret_arn"],
    }
    assert td["executionRoleArn"] == config["execution_role_arn"]


def test_jobs_run_as_the_right_database_role() -> None:
    config = deploy_config()
    migrate = ed.render(ctx(), "migrate", config, release())["containerDefinitions"][0]
    seed = ed.render(ctx(), "seed", config, release())["containerDefinitions"][0]
    assert migrate["command"] == ["alembic", "upgrade", "head"]
    assert env_of(migrate)["DB_USER"] == "dora_owner"
    assert secrets_of(migrate)["DB_PASSWORD"] == config["db_owner_secret_arn"] + ":password::"
    assert env_of(seed)["DB_USER"] == "dora_app"
    assert secrets_of(seed)["DB_PASSWORD"] == config["db_app_secret_arn"] + ":password::"
    assert migrate["logConfiguration"]["options"]["awslogs-group"] == "/loria-dora/dev/jobs"


def test_only_db_bootstrap_reads_the_master_secret() -> None:
    config = deploy_config()
    td = ed.render(ctx(), "db-bootstrap", config, release())
    (container,) = td["containerDefinitions"]
    assert container["image"] == release()["images"]["dbinit"]
    assert td["executionRoleArn"] == config["db_bootstrap_execution_role_arn"]
    master = config["db_master_secret_arn"]
    assert secrets_of(container) == {
        "PGUSER": f"{master}:username::",
        "PGPASSWORD": f"{master}:password::",
        "DORA_OWNER_PASSWORD": config["db_owner_secret_arn"] + ":password::",
        "DORA_APP_PASSWORD": config["db_app_secret_arn"] + ":password::",
    }
    for family in ("app", "migrate", "seed"):
        assert master not in json.dumps(ed.render(ctx(), family, config, release()))


def test_render_escapes_values_and_names_a_missing_one() -> None:
    config = deploy_config()
    config["db_host"] = 'db"host'
    td = ed.render(ctx(), "migrate", config, release())
    assert env_of(td["containerDefinitions"][0])["DB_HOST"] == 'db"host'
    del config["db_host"]
    with pytest.raises(ed.DeployError, match="needs DB_HOST"):
        ed.render(ctx(), "migrate", config, release())


def test_ca_bundle_path_and_pin_agree_across_images_and_templates() -> None:
    api_df = (REPO_ROOT / "api" / "Dockerfile").read_text()
    db_df = (REPO_ROOT / "db" / "Dockerfile").read_text()
    pattern = re.compile(r"--checksum=(sha256:[0-9a-f]{64}).*?\n?.*?global-bundle\.pem (\S+)")
    api_pin, db_pin = pattern.search(api_df), pattern.search(db_df)
    assert api_pin
    assert db_pin
    assert api_pin.groups() == db_pin.groups()  # same checksum, same destination
    bundle = api_pin.group(2)
    app = ed.render(ctx(), "app", deploy_config(), release())
    assert env_of(app["containerDefinitions"][0])["DB_SSL_ROOT_CERT"] == bundle
    run_bootstrap = (REPO_ROOT / "db" / "run-bootstrap.sh").read_text()
    assert f"PGSSLROOTCERT:-{bundle}" in run_bootstrap


def test_register_sends_the_rendered_definition_and_returns_its_arn(fake: FakeAws) -> None:
    config = deploy_config()
    task_arn = ed.register(aws(fake), ctx(), "migrate", config, release())
    assert task_arn == arn("ecs", "task-definition/loria-dora-dev-migrate:1")
    assert fake.registered == [ed.render(ctx(), "migrate", config, release())]


# ---- one-off tasks ----


def test_run_task_waits_prints_logs_and_succeeds_on_exit_0(
    fake: FakeAws, capsys: pytest.CaptureFixture[str]
) -> None:
    config = deploy_config()
    td = arn("ecs", "task-definition/loria-dora-dev-migrate:3")
    ed.run_task(aws(fake), config, td, started_by="run-42")
    assert ops(fake) == [
        "ecs run-task",
        "ecs wait",
        "ecs describe-tasks",
        "logs get-log-events",
    ]
    run = fake.calls[0]
    network = json.loads(run[run.index("--network-configuration") + 1])["awsvpcConfiguration"]
    assert network == {
        "subnets": ["subnet-aaa", "subnet-bbb"],
        "securityGroups": ["sg-123"],
        "assignPublicIp": "DISABLED",
    }
    assert run[run.index("--launch-type") + 1] == "FARGATE"
    logs = fake.calls[3]
    assert logs[logs.index("--log-stream-name") + 1] == "migrate/migrate/0123456789abcdef"
    assert "INFO upgrade done" in capsys.readouterr().err


def test_run_task_fails_on_a_nonzero_exit_with_the_reason(fake: FakeAws) -> None:
    fake.task_exit_code = 1
    td = arn("ecs", "task-definition/loria-dora-dev-migrate:3")
    with pytest.raises(ed.DeployError, match="migrate exited with 1: Essential container"):
        ed.run_task(aws(fake), deploy_config(), td)


def test_run_task_fails_when_the_container_never_ran(fake: FakeAws) -> None:
    fake.task_exit_code = None
    fake.task_reason = "CannotPullContainerError: pull access denied"
    fake.log_events = []  # no stream was ever created; that's not a second failure
    td = arn("ecs", "task-definition/loria-dora-dev-db-bootstrap:1")
    with pytest.raises(ed.DeployError, match="exited with None: CannotPullContainerError"):
        ed.run_task(aws(fake), deploy_config(), td)


# ---- rollout and publish ----


def test_first_rollout_scales_the_service_up_from_zero(fake: FakeAws) -> None:
    config = deploy_config()
    td = arn("ecs", "task-definition/loria-dora-dev-app:2")
    ed.rollout(aws(fake), config, td)
    update = next(c for c in fake.calls if c[1] == "update-service")
    assert update[update.index("--desired-count") + 1] == "1"
    assert fake.services["loria-dora-dev-app"]["taskDefinition"] == td


def test_later_rollouts_leave_the_desired_count_alone(fake: FakeAws) -> None:
    fake.services["loria-dora-dev-app"]["desiredCount"] = 3
    ed.rollout(aws(fake), deploy_config(), arn("ecs", "task-definition/loria-dora-dev-app:5"))
    update = next(c for c in fake.calls if c[1] == "update-service")
    assert "--desired-count" not in update


def test_rollout_fails_when_the_circuit_breaker_rolled_back(fake: FakeAws) -> None:
    fake.unhealthy_rollout = True
    with pytest.raises(ed.DeployError, match="circuit breaker rolled back"):
        ed.rollout(aws(fake), deploy_config(), arn("ecs", "task-definition/loria-dora-dev-app:2"))


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    slept: list[float] = []
    monkeypatch.setattr(ed.time, "sleep", slept.append)
    return slept


def test_rollout_waits_while_a_stable_deployment_is_still_in_progress(
    fake: FakeAws, no_sleep: list[float]
) -> None:
    # The first deploy's real failure: services-stable returned while ECS still
    # reported the new, healthy deployment IN_PROGRESS.
    fake.rollout_in_progress_for = 2
    td = arn("ecs", "task-definition/loria-dora-dev-app:3")
    ed.rollout(aws(fake), deploy_config(), td)
    assert no_sleep == [ed.ROLLOUT_POLL_S, ed.ROLLOUT_POLL_S]


def test_rollout_fails_when_the_deployment_fails(fake: FakeAws, no_sleep: list[float]) -> None:
    fake.rollout_final_state = "FAILED"
    with pytest.raises(ed.DeployError, match=r"rollout of .* failed: ECS deployment circuit"):
        ed.rollout(aws(fake), deploy_config(), arn("ecs", "task-definition/loria-dora-dev-app:3"))


def test_rollout_gives_up_if_it_never_completes(
    fake: FakeAws, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.rollout_in_progress_for = 10**6
    clock = iter(range(0, 10**6, 60))
    monkeypatch.setattr(ed.time, "monotonic", lambda: float(next(clock)))
    monkeypatch.setattr(ed.time, "sleep", lambda _s: None)
    with pytest.raises(ed.DeployError, match="still IN_PROGRESS after 600 s"):
        ed.rollout(aws(fake), deploy_config(), arn("ecs", "task-definition/loria-dora-dev-app:3"))


def test_publish_overwrites_the_release_pointer(fake: FakeAws) -> None:
    ed.publish(aws(fake), ctx(), V2)
    assert fake.params["/loria-dora/dev/release-version"][-1] == V2


# ---- rollback rules ----


@pytest.fixture
def history_repo(repo: Repo) -> dict[str, str]:
    """Three commits: SHA of each release, where release 2 adds a migration."""
    one = write(repo, "api/app.py", "v1", "release 1")
    two = write(repo, "api/alembic/versions/0002_x.py", "m2", "release 2: migration")
    three = write(repo, "api/app.py", "v3", "release 3")
    return {V1: one, V2: two, V3: three}


def rollback_fake(commits: dict[str, str]) -> FakeAws:
    fake = FakeAws()
    fake.environment("dev")
    for version, sha in commits.items():
        fake.release(version, sha)
    fake.history("dev", V1, V2, V3)
    return fake


def resolve(fake: FakeAws, repo: Repo, env: str = "dev", **kwargs: Any) -> dict[str, Any]:
    kwargs.setdefault("target", "previous")
    kwargs.setdefault("reason", "errors after deploy")
    return ed.resolve_rollback(aws(fake), ctx(env), repo=repo.path, **kwargs)


def test_rollback_defaults_to_the_previous_release(
    history_repo: dict[str, str], repo: Repo
) -> None:
    fake = rollback_fake(history_repo)
    result = resolve(fake, repo)
    assert (result["from"], result["version"]) == (V3, V2)
    assert result["commit"] == history_repo[V2]
    assert result["images"]["api"].endswith(digest("api", V2))


def test_rollback_across_a_migration_needs_the_flag_unless_previous(
    history_repo: dict[str, str], repo: Repo
) -> None:
    fake = rollback_fake(history_repo)
    # V3 -> V1 crosses release 2's migration and V1 isn't the previous release.
    with pytest.raises(ed.DeployError, match="Migrations differ"):
        resolve(fake, repo, target=V1)
    assert resolve(fake, repo, target=V1, allow_schema_change=True)["version"] == V1


def test_rollback_to_a_release_with_the_same_migrations_needs_no_flag(
    history_repo: dict[str, str], repo: Repo
) -> None:
    fake = rollback_fake(history_repo)
    fake.history("dev", V2, V1, V3)  # running V3; V2, two back, has the same migrations
    assert resolve(fake, repo, target=V2)["version"] == V2


def test_rollback_by_release_tag(history_repo: dict[str, str], repo: Repo) -> None:
    fake = rollback_fake(history_repo)
    assert resolve(fake, repo, target=f"release-{V2}")["version"] == V2


def test_rollback_by_commit_sha(history_repo: dict[str, str], repo: Repo) -> None:
    fake = rollback_fake(history_repo)
    result = resolve(fake, repo, target=history_repo[V2])
    assert result["version"] == V2
    with pytest.raises(ed.DeployError, match="No release was built from commit"):
        resolve(fake, repo, target="f" * 40)


def test_rollback_rules_refuse_unsafe_targets(history_repo: dict[str, str], repo: Repo) -> None:
    fake = rollback_fake(history_repo)
    with pytest.raises(ed.DeployError, match="needs a reason"):
        resolve(fake, repo, reason="  ")
    with pytest.raises(ed.DeployError, match="already running"):
        resolve(fake, repo, target=V3)
    with pytest.raises(ed.DeployError, match="must be 'previous'"):
        resolve(fake, repo, target="v1.2.3")

    fake.release("ddddddddddd4", SHA3, images=("api",))
    with pytest.raises(ed.DeployError, match="has no web, dbinit image"):
        resolve(fake, repo, target="ddddddddddd4")


def test_only_dev_may_roll_back_to_an_unproven_release(
    history_repo: dict[str, str], repo: Repo
) -> None:
    fake = rollback_fake(history_repo)
    fake.history("dev", V2, V3)  # V1 has never run here
    with pytest.raises(ed.DeployError, match="never run in dev"):
        resolve(fake, repo, target=V1, allow_schema_change=True)
    assert (
        resolve(fake, repo, target=V1, allow_schema_change=True, allow_unproven=True)["version"]
        == V1
    )

    fake.environment("stage")
    fake.history("stage", V2, V3)
    with pytest.raises(ed.DeployError, match="Only dev"):
        resolve(fake, repo, env="stage", target=V1, allow_unproven=True)


def test_rollback_needs_a_deployed_environment_with_history(repo: Repo) -> None:
    fake = FakeAws()
    fake.environment("dev")
    with pytest.raises(ed.DeployError, match="never been deployed"):
        resolve(fake, repo)
    fake.history("dev", V1)
    with pytest.raises(ed.DeployError, match="no earlier release"):
        resolve(fake, repo)


# ---- the CLI ----


def env_vars(env: str = "dev") -> dict[str, str]:
    return {"NAME_PREFIX": PREFIX, "AWS_REGION": REGION, "ENVIRONMENT": env}


def test_cli_prints_json_and_reports_failures_as_github_errors(
    fake: FakeAws, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    fake.release(V1, SHA1)
    assert ed.main(["preflight", "--version", V1], env_vars(), fake) == 0
    out = capsys.readouterr().out
    release_file = tmp_path / "release.json"
    release_file.write_text(out)
    assert json.loads(out)["version"] == V1

    assert (
        ed.main(["register", "--family", "app", "--release", str(release_file)], env_vars(), fake)
        == 0
    )
    assert capsys.readouterr().out.strip() == arn("ecs", "task-definition/loria-dora-dev-app:1")

    assert ed.main(["preflight", "--version", V2], env_vars(), fake) == 1
    assert "::error::Release bbbbbbbbbbb2 has no api, web, dbinit image" in capsys.readouterr().err


def test_cli_rejects_a_bad_environment(capsys: pytest.CaptureFixture[str]) -> None:
    assert ed.main(["publish", "--version", V1], env_vars("qa"), FakeAws()) == 1
    assert "dev, stage, or prod" in capsys.readouterr().err


def test_run_aws_raises_with_the_error_code(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            [], 254, "", "An error occurred (ParameterNotFound) when calling GetParameter"
        )

    monkeypatch.setattr(ed.subprocess, "run", fake_run)
    with pytest.raises(ed.AwsError) as info:
        ed.run_aws(["ssm", "get-parameter", "--name", "x"])
    assert info.value.code == "ParameterNotFound"


def test_infra_publishes_exactly_the_deploy_config_keys_the_scripts_need() -> None:
    main_tf = (REPO_ROOT / "infra" / "env" / "main.tf").read_text()
    block = main_tf.split('resource "aws_ssm_parameter" "deploy_config"', 1)[1]
    body = block.split("jsonencode({", 1)[1].split("})", 1)[0]
    published = re.findall(r"^\s*(\w+)\s*=", body, flags=re.MULTILINE)
    assert sorted(published) == sorted(ed.CONFIG_KEYS)
