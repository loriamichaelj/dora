# Deploy roles assumed by GitHub Actions via OIDC (docs/CLOUD-DEVOPS-DESIGN.md §5.3).
#
#   <iam_name_prefix>-deploy-{dev,stage,prod}  one environment: infra/env Terraform,
#                                              deploys, rollbacks, one-off tasks
#   <iam_name_prefix>-deploy-shared            the network (and later DNS)
#
# Each role trusts exactly one GitHub Environment. Permissions are scoped by
# name pattern (<name_prefix>-<env>-*, <iam_name_prefix>-<env>-*) where the
# service supports resource ARNs, and by the Environment + Project tags where
# only IDs exist (EC2). The account is shared, so every tag condition checks
# Project too: another project's Environment=dev resources must stay out of
# reach. Read-only Describe/List calls are the only unscoped actions, and each
# other unscoped action says why.
#
# Policy size: managed policies cap at 6,144 characters, so each role's
# permissions are split across several policies by concern.

locals {
  tfstate_arn = "arn:${local.partition}:s3:::${var.state_bucket}"
  iam_prefix  = "arn:${local.partition}:iam::${local.account_id}"

  # n: resource names/paths; iam_n: IAM names (see infra/project.env).
  n     = var.name_prefix
  iam_n = var.iam_name_prefix

  arn_ec2     = "arn:${local.partition}:ec2:${var.aws_region}:${local.account_id}"
  arn_ecs     = "arn:${local.partition}:ecs:${var.aws_region}:${local.account_id}"
  arn_ecr     = "arn:${local.partition}:ecr:${var.aws_region}:${local.account_id}"
  arn_elb     = "arn:${local.partition}:elasticloadbalancing:${var.aws_region}:${local.account_id}"
  arn_logs    = "arn:${local.partition}:logs:${var.aws_region}:${local.account_id}"
  arn_rds     = "arn:${local.partition}:rds:${var.aws_region}:${local.account_id}"
  arn_secrets = "arn:${local.partition}:secretsmanager:${var.aws_region}:${local.account_id}"
  arn_ssm     = "arn:${local.partition}:ssm:${var.aws_region}:${local.account_id}"

  ecr_repos = "${local.arn_ecr}:repository/${local.n}/*"

  # The environment whose release-version the preflight check reads (§7.2
  # step 4): prod may only deploy exactly what stage runs. Stage checks ECR
  # instead, so it reads nothing upstream.
  upstream_environment = { dev = null, stage = null, prod = "stage" }

  deploy_policy_kinds = ["network", "iam", "services", "containers", "state"]
}

# --- Trust --------------------------------------------------------------------

data "aws_iam_policy_document" "github_trust" {
  for_each = setunion(local.app_environments, ["shared"])

  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [data.aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["${var.github_oidc_sub_prefix}:environment:${each.key}"]
    }
  }
}

# --- Task permissions boundary --------------------------------------------------
# Every IAM role a deploy role creates (each environment's ECS task and task
# execution roles) must carry this boundary. Without it, a role that can
# create roles and write their policies could grant itself anything. It's the
# most any container, or ECS acting for one, can ever do: pull Dora's images,
# write Dora's logs, and read Dora's secrets. The app itself calls no AWS API.

resource "aws_iam_policy" "task_boundary" {
  name        = "${local.iam_n}-task-boundary"
  description = "Upper bound on permissions for Dora ECS task and task execution roles."
  policy      = data.aws_iam_policy_document.task_boundary.json
}

data "aws_iam_policy_document" "task_boundary" {
  # Has no resource-level control; it only issues a registry login token.
  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "EcrPull"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [local.ecr_repos]
  }

  statement {
    sid       = "ShipLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${local.arn_logs}:log-group:/${local.n}/*"]
  }

  statement {
    sid       = "ReadProjectSecrets"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["${local.arn_secrets}:secret:${local.n}/*"]
  }

  # The RDS-managed master secret is named rds!db-<uuid>, so it can't be
  # scoped by name; RDS tags it with the owning instance's ARN instead. Only
  # the db-bootstrap task's execution role is given it (infra/env).
  statement {
    sid       = "ReadRdsMasterSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["${local.arn_secrets}:secret:rds!db-*"]
    condition {
      test     = "StringLike"
      variable = "aws:ResourceTag/aws:rds:primaryDBInstanceArn"
      values   = ["${local.arn_rds}:db:${local.n}-*"]
    }
  }
}

# --- Per-environment deploy roles ---------------------------------------------

resource "aws_iam_role" "env" {
  for_each = local.app_environments

  name                 = "${local.iam_n}-deploy-${each.key}"
  description          = "GitHub Actions (Environment ${each.key}): infra/env Terraform, deploys, rollbacks, one-off tasks."
  assume_role_policy   = data.aws_iam_policy_document.github_trust[each.key].json
  max_session_duration = 3600

  tags = { Environment = each.key }
}

resource "aws_iam_policy" "env" {
  for_each = {
    for pair in setproduct(local.app_environments, local.deploy_policy_kinds) :
    "${pair[0]}-${pair[1]}" => { env = pair[0], kind = pair[1] }
  }

  name = "${local.iam_n}-deploy-${each.key}"
  policy = {
    network    = data.aws_iam_policy_document.env_network
    iam        = data.aws_iam_policy_document.env_iam
    services   = data.aws_iam_policy_document.env_services
    containers = data.aws_iam_policy_document.env_containers
    state      = data.aws_iam_policy_document.env_state
  }[each.value.kind][each.value.env].json
  tags = { Environment = each.value.env }
}

resource "aws_iam_role_policy_attachment" "env" {
  for_each = aws_iam_policy.env

  role       = aws_iam_role.env[split("-", each.key)[0]].name
  policy_arn = each.value.arn
}

# Read-only calls, and the environment's security groups (tag-scoped).
data "aws_iam_policy_document" "env_network" {
  for_each = local.app_environments

  statement {
    sid = "ReadOnly"
    actions = [
      "ec2:Describe*",
      "ecs:Describe*",
      "ecs:List*",
      "elasticloadbalancing:Describe*",
      "rds:Describe*",
      "rds:ListTagsForResource",
      "logs:DescribeLogGroups",
      "ssm:DescribeParameters",
      "secretsmanager:ListSecrets",
      "kms:DescribeKey",
      "kms:ListAliases",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "SecurityGroupCreateTagged"
    actions   = ["ec2:CreateSecurityGroup"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Environment"
      values   = [each.key]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Project"
      values   = [local.n]
    }
  }

  statement {
    sid       = "SecurityGroupTagOnCreate"
    actions   = ["ec2:CreateTags"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "ec2:CreateAction"
      values   = ["CreateSecurityGroup"]
    }
  }

  # CreateSecurityGroup is also authorized against the VPC it goes in: the
  # shared VPC (Environment=shared, this Project only).
  statement {
    sid       = "SecurityGroupInSharedVpc"
    actions   = ["ec2:CreateSecurityGroup"]
    resources = ["${local.arn_ec2}:vpc/*"]
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Environment"
      values   = ["shared"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Project"
      values   = [local.n]
    }
  }

  statement {
    sid = "SecurityGroupManageOwn"
    actions = [
      "ec2:AuthorizeSecurityGroupIngress",
      "ec2:AuthorizeSecurityGroupEgress",
      "ec2:RevokeSecurityGroupIngress",
      "ec2:RevokeSecurityGroupEgress",
      "ec2:ModifySecurityGroupRules",
      "ec2:UpdateSecurityGroupRuleDescriptionsIngress",
      "ec2:UpdateSecurityGroupRuleDescriptionsEgress",
      "ec2:DeleteSecurityGroup",
      "ec2:CreateTags",
      "ec2:DeleteTags",
    ]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Environment"
      values   = [each.key]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Project"
      values   = [local.n]
    }
  }
}

# The environment's task and task execution roles (boundary-enforced), and
# the service-linked roles and KMS grants the managed services need.
data "aws_iam_policy_document" "env_iam" {
  for_each = local.app_environments

  statement {
    sid = "TaskRolesWithBoundary"
    actions = [
      "iam:CreateRole",
      "iam:PutRolePermissionsBoundary",
      "iam:PutRolePolicy",
      "iam:DeleteRolePolicy",
      "iam:AttachRolePolicy",
      "iam:DetachRolePolicy",
    ]
    resources = ["${local.iam_prefix}:role/${local.iam_n}-${each.key}-*"]
    condition {
      test     = "StringEquals"
      variable = "iam:PermissionsBoundary"
      values   = [aws_iam_policy.task_boundary.arn]
    }
  }

  statement {
    sid = "TaskRolesManage"
    actions = [
      "iam:GetRole",
      "iam:DeleteRole",
      "iam:UpdateRole",
      "iam:UpdateRoleDescription",
      "iam:UpdateAssumeRolePolicy",
      "iam:TagRole",
      "iam:UntagRole",
      "iam:ListRoleTags",
      "iam:GetRolePolicy",
      "iam:ListRolePolicies",
      "iam:ListAttachedRolePolicies",
      "iam:ListInstanceProfilesForRole",
    ]
    resources = ["${local.iam_prefix}:role/${local.iam_n}-${each.key}-*"]
  }

  statement {
    sid       = "PassTaskRolesToEcs"
    actions   = ["iam:PassRole"]
    resources = ["${local.iam_prefix}:role/${local.iam_n}-${each.key}-*"]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }

  statement {
    sid       = "ServiceLinkedRoles"
    actions   = ["iam:CreateServiceLinkedRole"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "iam:AWSServiceName"
      values = [
        "ecs.amazonaws.com",
        "elasticloadbalancing.amazonaws.com",
        "rds.amazonaws.com",
      ]
    }
  }

  # RDS encrypts storage with the account's default aws/rds key, through a
  # grant it creates on the caller's behalf.
  statement {
    sid       = "RdsEncryptionViaService"
    actions   = ["kms:CreateGrant", "kms:DescribeKey"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["rds.${var.aws_region}.amazonaws.com"]
    }
  }
}

# ALB, RDS, secrets, SSM parameters, and log groups: all name-scoped to
# <name_prefix>-<env>-* or <name_prefix>/<env>/*.
data "aws_iam_policy_document" "env_services" {
  for_each = local.app_environments

  statement {
    sid     = "LoadBalancer"
    actions = ["elasticloadbalancing:*"]
    resources = [
      "${local.arn_elb}:loadbalancer/app/${local.n}-${each.key}-*/*",
      "${local.arn_elb}:targetgroup/${local.n}-${each.key}-*/*",
      "${local.arn_elb}:listener/app/${local.n}-${each.key}-*/*",
      "${local.arn_elb}:listener-rule/app/${local.n}-${each.key}-*/*",
    ]
  }

  statement {
    sid     = "Database"
    actions = ["rds:*"]
    resources = [
      "${local.arn_rds}:db:${local.n}-${each.key}-*",
      "${local.arn_rds}:subgrp:${local.n}-${each.key}-*",
      "${local.arn_rds}:pg:${local.n}-${each.key}-*",
      "${local.arn_rds}:snapshot:${local.n}-${each.key}-*",
      # AWS-owned default option group every PostgreSQL instance uses; it
      # can't be modified, only referenced.
      "${local.arn_rds}:og:default:*",
    ]
  }

  # db-owner, db-app, ingest-api-key. The deploy role reads the ingest key
  # itself, for self-tracking (§7.6).
  statement {
    sid       = "EnvSecrets"
    actions   = ["secretsmanager:*"]
    resources = ["${local.arn_secrets}:secret:${local.n}/${each.key}/*"]
  }

  # With manage_master_user_password, RDS creates and rotates the master
  # secret (rds!db-<uuid>) using the caller's permissions. Its name can't be
  # scoped; creating one is harmless, and everything after creation is limited
  # to secrets tagged with this environment's instance.
  statement {
    sid       = "RdsMasterSecretCreate"
    actions   = ["secretsmanager:CreateSecret", "secretsmanager:TagResource"]
    resources = ["${local.arn_secrets}:secret:rds!db-*"]
  }

  statement {
    sid = "RdsMasterSecretManage"
    actions = [
      "secretsmanager:DescribeSecret",
      "secretsmanager:RotateSecret",
      "secretsmanager:DeleteSecret",
    ]
    resources = ["${local.arn_secrets}:secret:rds!db-*"]
    condition {
      test     = "StringLike"
      variable = "aws:ResourceTag/aws:rds:primaryDBInstanceArn"
      values   = ["${local.arn_rds}:db:${local.n}-${each.key}-*"]
    }
  }

  statement {
    sid = "EnvParameters"
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:GetParameterHistory",
      "ssm:PutParameter",
      "ssm:DeleteParameter",
      "ssm:DeleteParameters",
      "ssm:AddTagsToResource",
      "ssm:RemoveTagsFromResource",
      "ssm:ListTagsForResource",
    ]
    resources = ["${local.arn_ssm}:parameter/${local.n}/${each.key}/*"]
  }

  dynamic "statement" {
    for_each = local.upstream_environment[each.key] == null ? [] : [local.upstream_environment[each.key]]
    content {
      sid       = "ReadUpstreamReleaseVersion"
      actions   = ["ssm:GetParameter"]
      resources = ["${local.arn_ssm}:parameter/${local.n}/${statement.value}/release-version"]
    }
  }

  statement {
    sid       = "LogGroups"
    actions   = ["logs:*"]
    resources = ["${local.arn_logs}:log-group:/${local.n}/${each.key}/*"]
  }
}

# The ECS cluster, service, task definitions, and one-off tasks; ECR images.
data "aws_iam_policy_document" "env_containers" {
  for_each = local.app_environments

  statement {
    sid     = "ClusterServiceTasks"
    actions = ["ecs:*"]
    resources = [
      "${local.arn_ecs}:cluster/${local.n}-${each.key}",
      "${local.arn_ecs}:service/${local.n}-${each.key}/*",
      "${local.arn_ecs}:task/${local.n}-${each.key}/*",
    ]
  }

  # RegisterTaskDefinition has no resource-level control, so it's bound by
  # the tags every revision must carry instead (families are prefixed
  # <name_prefix>-<env>-).
  statement {
    sid       = "TaskDefinitionRegisterTagged"
    actions   = ["ecs:RegisterTaskDefinition"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Environment"
      values   = [each.key]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Project"
      values   = [local.n]
    }
  }

  # Deregistering and deleting a task definition are authorized against `*`,
  # not the revision's ARN (the ARN form is denied), so they can't be scoped to
  # this environment's families. Terraform needs them to destroy the
  # placeholder task definition.
  statement {
    sid = "TaskDefinitionDeregister"
    actions = [
      "ecs:DeregisterTaskDefinition",
      "ecs:DeleteTaskDefinitions",
    ]
    resources = ["*"]
  }

  statement {
    sid = "TaskDefinitionManageOwn"
    actions = [
      "ecs:TagResource",
      "ecs:UntagResource",
      "ecs:ListTagsForResource",
    ]
    resources = ["${local.arn_ecs}:task-definition/${local.n}-${each.key}-*:*"]
  }

  # One-off tasks (db-bootstrap, migrate, seed): only this environment's
  # families, and only on this environment's cluster.
  statement {
    sid       = "RunOwnTasksOnOwnCluster"
    actions   = ["ecs:RunTask"]
    resources = ["${local.arn_ecs}:task-definition/${local.n}-${each.key}-*:*"]
    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values   = ["${local.arn_ecs}:cluster/${local.n}-${each.key}"]
    }
  }

  statement {
    sid = "ImagesRead"
    actions = [
      "ecr:DescribeRepositories",
      "ecr:DescribeImages",
      "ecr:ListImages",
      "ecr:BatchGetImage",
      "ecr:DescribeImageScanFindings",
    ]
    resources = [local.ecr_repos]
  }

  # Build once (§2, C6): only dev ever pushes images. Stage and prod can
  # only look them up.
  dynamic "statement" {
    for_each = each.key == "dev" ? [1] : []
    content {
      sid       = "RegistryLogin"
      actions   = ["ecr:GetAuthorizationToken"] # no resource-level control
      resources = ["*"]
    }
  }

  dynamic "statement" {
    for_each = each.key == "dev" ? [1] : []
    content {
      sid = "ImagesPush"
      actions = [
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
        "ecr:PutImage",
      ]
      resources = [local.ecr_repos]
    }
  }
}

# Terraform state: this environment's keys, plus reading the network's.
data "aws_iam_policy_document" "env_state" {
  for_each = local.app_environments

  statement {
    sid       = "StateList"
    actions   = ["s3:ListBucket"]
    resources = [local.tfstate_arn]
  }

  statement {
    sid       = "StateOwn"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${local.tfstate_arn}/env:/${each.key}/*"]
  }

  statement {
    sid       = "StateReadNetwork"
    actions   = ["s3:GetObject"]
    resources = ["${local.tfstate_arn}/env:/shared/network.tfstate"]
  }
}

# --- Shared role: the network (and later DNS) -----------------------------------
# DNS permissions (§6.10) are added in the step that introduces infra/dns;
# bootstrap.yml re-applies this file.

resource "aws_iam_role" "shared" {
  name                 = "${local.iam_n}-deploy-shared"
  description          = "GitHub Actions (Environment shared): the network, and later DNS."
  assume_role_policy   = data.aws_iam_policy_document.github_trust["shared"].json
  max_session_duration = 3600
}

resource "aws_iam_policy" "shared_network" {
  name   = "${local.iam_n}-deploy-shared-network"
  policy = data.aws_iam_policy_document.shared_network.json
}

resource "aws_iam_role_policy_attachment" "shared_network" {
  role       = aws_iam_role.shared.name
  policy_arn = aws_iam_policy.shared_network.arn
}

data "aws_iam_policy_document" "shared_network" {
  statement {
    sid       = "ReadOnly"
    actions   = ["ec2:Describe*"]
    resources = ["*"]
  }

  statement {
    sid = "NetworkCreateTagged"
    actions = [
      "ec2:CreateVpc",
      "ec2:CreateSubnet",
      "ec2:CreateInternetGateway",
      "ec2:CreateRouteTable",
      "ec2:CreateSecurityGroup",
      "ec2:CreateVpcEndpoint",
    ]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Environment"
      values   = ["shared"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Project"
      values   = [local.n]
    }
  }

  statement {
    sid       = "NetworkTagOnCreate"
    actions   = ["ec2:CreateTags"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "ec2:CreateAction"
      values = [
        "CreateVpc",
        "CreateSubnet",
        "CreateInternetGateway",
        "CreateRouteTable",
        "CreateSecurityGroup",
        "CreateVpcEndpoint",
      ]
    }
  }

  # Everything the network root does to resources it already owns: routes,
  # associations, attachments, attribute changes, deletes. Bounded by the
  # Environment=shared + Project tags, which only this role can set.
  statement {
    sid       = "NetworkManageOwn"
    actions   = ["ec2:*"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Environment"
      values   = ["shared"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Project"
      values   = [local.n]
    }
  }

  statement {
    sid       = "EndpointServiceLinkedRole"
    actions   = ["iam:CreateServiceLinkedRole"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "iam:AWSServiceName"
      values   = ["vpcendpoint.amazonaws.com"]
    }
  }

  # Interface endpoints with private DNS attach the VPC to an AWS-managed
  # private hosted zone; AWS checks these as dependent actions of
  # CreateVpcEndpoint / DeleteVpcEndpoints. Not tag-scoped (Route 53 hosted
  # zones don't support it); the role can't create or edit zones or records.
  statement {
    sid = "EndpointPrivateDns"
    actions = [
      "route53:AssociateVPCWithHostedZone",
      "route53:DisassociateVPCFromHostedZone",
    ]
    resources = [
      "arn:${local.partition}:route53:::hostedzone/*",
      "${local.arn_ec2}:vpc/*",
    ]
  }

  statement {
    sid       = "StateList"
    actions   = ["s3:ListBucket"]
    resources = [local.tfstate_arn]
  }

  statement {
    sid       = "StateNetwork"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${local.tfstate_arn}/env:/shared/network.tfstate*"]
  }
}
