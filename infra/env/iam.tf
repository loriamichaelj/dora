# ECS task and execution roles (docs/CLOUD-DEVOPS-DESIGN.md §5.3, C19). Every
# role here carries the task permissions boundary from infra/bootstrap; the
# deploy role can't create one without it.
#
#   <iam_prefix>-<env>-task               the containers' own role: grants nothing,
#                                         because the app calls no AWS API
#   <iam_prefix>-<env>-task-exec          ECS, for app, migrate, and seed: pull
#                                         images, write logs, inject their secrets
#   <iam_prefix>-<env>-db-bootstrap-exec  ECS, for db-bootstrap only: the same,
#                                         plus the RDS master secret

data "aws_iam_policy_document" "ecs_tasks_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
    # Only ECS acting for this account (the confused-deputy guard).
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_iam_role" "task" {
  name                 = "${local.iam_n}-${local.env}-task"
  description          = "${local.env} ECS tasks. Grants nothing: the app calls no AWS API."
  assume_role_policy   = data.aws_iam_policy_document.ecs_tasks_trust.json
  permissions_boundary = local.task_boundary_arn
}

resource "aws_iam_role" "task_exec" {
  name                 = "${local.iam_n}-${local.env}-task-exec"
  description          = "ECS for ${local.env} app, migrate, and seed tasks: images, logs, their secrets."
  assume_role_policy   = data.aws_iam_policy_document.ecs_tasks_trust.json
  permissions_boundary = local.task_boundary_arn
}

resource "aws_iam_role" "db_bootstrap_exec" {
  name                 = "${local.iam_n}-${local.env}-db-bootstrap-exec"
  description          = "ECS for the ${local.env} db-bootstrap task: images, logs, and the RDS master secret."
  assume_role_policy   = data.aws_iam_policy_document.ecs_tasks_trust.json
  permissions_boundary = local.task_boundary_arn
}

locals {
  ecr_repos = "arn:${local.partition}:ecr:${var.aws_region}:${local.account_id}:repository/${local.n}/*"
}

data "aws_iam_policy_document" "task_exec" {
  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"] # no resource-level control
    resources = ["*"]
  }

  statement {
    sid = "PullImages"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [local.ecr_repos]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = [for g in aws_cloudwatch_log_group.this : "${g.arn}:*"]
  }

  statement {
    sid     = "InjectSecrets"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_secretsmanager_secret.this["db-owner"].arn,
      aws_secretsmanager_secret.this["db-app"].arn,
      aws_secretsmanager_secret.this["ingest-api-key"].arn,
    ]
  }
}

data "aws_iam_policy_document" "db_bootstrap_exec" {
  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"] # no resource-level control
    resources = ["*"]
  }

  statement {
    sid = "PullImages"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [local.ecr_repos]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.this["jobs"].arn}:*"]
  }

  statement {
    sid     = "InjectSecrets"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_db_instance.this.master_user_secret[0].secret_arn,
      aws_secretsmanager_secret.this["db-owner"].arn,
      aws_secretsmanager_secret.this["db-app"].arn,
    ]
  }
}

resource "aws_iam_role_policy" "task_exec" {
  name   = "ecs-execution"
  role   = aws_iam_role.task_exec.id
  policy = data.aws_iam_policy_document.task_exec.json
}

resource "aws_iam_role_policy" "db_bootstrap_exec" {
  name   = "ecs-execution"
  role   = aws_iam_role.db_bootstrap_exec.id
  policy = data.aws_iam_policy_document.db_bootstrap_exec.json
}
