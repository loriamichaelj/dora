# Account-wide foundations (docs/CLOUD-DEVOPS-DESIGN.md §5.2). Applied only by
# bootstrap.yml, using the manually created bootstrap role.

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

# Exists once per account (it predates this project: Beacon uses it too);
# read here, never managed, since other projects in the account rely on it.
data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition

  app_environments = toset(["dev", "stage", "prod"])

  # Shared by every environment: images are built once, in dev, and promoted
  # by digest (§6.5, C6).
  ecr_repositories = toset(["api", "web", "dbinit"])
}

# --- Terraform state bucket -------------------------------------------------
# Created bare by ensure-state-bucket.sh (Terraform can't create the bucket
# its own state lives in), then adopted here so its settings are managed.

import {
  to = aws_s3_bucket.tfstate
  id = var.state_bucket
}

resource "aws_s3_bucket" "tfstate" {
  bucket = var.state_bucket

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket                  = aws_s3_bucket.tfstate.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  rule {
    id     = "expire-old-state-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }
}

resource "aws_s3_bucket_policy" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  policy = data.aws_iam_policy_document.tfstate_tls_only.json

  depends_on = [aws_s3_bucket_public_access_block.tfstate]
}

data "aws_iam_policy_document" "tfstate_tls_only" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      "arn:${local.partition}:s3:::${var.state_bucket}",
      "arn:${local.partition}:s3:::${var.state_bucket}/*",
    ]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

# --- ECR repositories ---------------------------------------------------------
# <name_prefix>/{api,web,dbinit}. Only deploy-dev can push (iam.tf), so stage
# and prod can only ever run images dev built. Tags are immutable: a release
# version or sha-<commit> tag always means the same image.

resource "aws_ecr_repository" "app" {
  for_each = local.ecr_repositories

  name                 = "${var.name_prefix}/${each.key}"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  # Holds every release still available as a rollback target.
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_lifecycle_policy" "app" {
  for_each = aws_ecr_repository.app

  repository = each.value.name
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Untagged images (superseded layers, failed pushes) after 1 day"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 1
        }
        action = { type = "expire" }
      },
      {
        # Each release is one image carrying two tags (<version>, sha-<commit>),
        # so this keeps the newest 50 releases.
        rulePriority = 2
        description  = "Keep the newest 50 releases as rollback targets"
        selection = {
          tagStatus      = "tagged"
          tagPatternList = ["*"]
          countType      = "imageCountMoreThan"
          countNumber    = 50
        }
        action = { type = "expire" }
      },
    ]
  })
}
