# One application environment (dev, stage, or prod) in the shared VPC
# (docs/CLOUD-DEVOPS-DESIGN.md §6): ALB -> ECS service on Fargate (web + api in
# one task) -> RDS for PostgreSQL. Applied by terraform.yml with target=infra,
# as the environment's own deploy role.
#
# Terraform owns the infrastructure and the service's existence; deploy.yml
# owns task-definition revisions, images, the desired count, and the
# release-version pointer (§7.4, C3).

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

data "terraform_remote_state" "network" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    key    = "env:/shared/network.tfstate"
    region = var.aws_region
  }
}

locals {
  n     = var.name_prefix
  iam_n = var.iam_name_prefix
  env   = var.environment

  # "<prefix>-<env>", e.g. loria-dora-dev. Every name below starts with it;
  # that's what the deploy role's IAM policy is scoped to.
  base = "${local.n}-${local.env}"

  account_id   = data.aws_caller_identity.current.account_id
  partition    = data.aws_partition.current.partition
  param_prefix = "/${local.n}/${local.env}"
  log_prefix   = "/${local.n}/${local.env}"

  # Created by infra/bootstrap; every role created here must carry it.
  task_boundary_arn = "arn:${local.partition}:iam::${local.account_id}:policy/${local.iam_n}-task-boundary"

  network            = data.terraform_remote_state.network.outputs
  vpc_id             = local.network.vpc_id
  vpc_cidr           = local.network.vpc_cidr
  public_subnet_ids  = local.network.public_subnet_ids[local.env]
  private_subnet_ids = local.network.private_subnet_ids[local.env]
}

# --- Log groups (§6.9) ------------------------------------------------------------
# Created here, not by ECS: the execution roles can only write to existing groups.

resource "aws_cloudwatch_log_group" "this" {
  for_each = toset(["app", "jobs"])

  name              = "${local.log_prefix}/${each.key}"
  retention_in_days = var.log_retention_days
}

# --- Release pointer (§7.2 step 9) --------------------------------------------------
# deploy.yml and rollback.yml own the value from here on; Terraform only
# creates it. "none" means nothing has been deployed yet.

resource "aws_ssm_parameter" "release_version" {
  name        = "${local.param_prefix}/release-version"
  description = "Release (content-hash version) that ${local.env} runs."
  type        = "String"
  value       = "none"

  lifecycle {
    ignore_changes = [value, insecure_value]
  }
}

# --- deploy-config (§6.8) -----------------------------------------------------------
# Everything the deploy scripts need from this root, in one parameter. The keys
# are the contract in deploy/ecs/README.md; scripts/deploy/ecs_deploy.py
# refuses to run if one is missing.

resource "aws_ssm_parameter" "deploy_config" {
  name        = "${local.param_prefix}/deploy-config"
  description = "Settings for deploying ${local.env} (deploy/ecs/README.md)."
  type        = "String"
  value = jsonencode({
    cluster                         = aws_ecs_cluster.this.name
    service                         = aws_ecs_service.app.name
    subnets                         = local.private_subnet_ids
    security_group                  = aws_security_group.task.id
    desired_count                   = var.app_desired_count
    cpu                             = tostring(var.app_cpu)
    memory                          = tostring(var.app_memory)
    task_role_arn                   = aws_iam_role.task.arn
    execution_role_arn              = aws_iam_role.task_exec.arn
    db_bootstrap_execution_role_arn = aws_iam_role.db_bootstrap_exec.arn
    app_log_group                   = aws_cloudwatch_log_group.this["app"].name
    jobs_log_group                  = aws_cloudwatch_log_group.this["jobs"].name
    db_host                         = aws_db_instance.this.address
    db_port                         = aws_db_instance.this.port
    db_name                         = aws_db_instance.this.db_name
    db_master_secret_arn            = aws_db_instance.this.master_user_secret[0].secret_arn
    db_owner_secret_arn             = aws_secretsmanager_secret.this["db-owner"].arn
    db_app_secret_arn               = aws_secretsmanager_secret.this["db-app"].arn
    ingest_api_key_secret_arn       = aws_secretsmanager_secret.this["ingest-api-key"].arn
    alb_dns_name                    = aws_lb.this.dns_name
  })
}
