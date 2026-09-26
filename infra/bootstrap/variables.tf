# Everything here except state_bucket comes from infra/project.env via
# TF_VAR_* (set by the workflow), so none of it has a default.

variable "aws_region" {
  type = string
}

variable "name_prefix" {
  description = "Prefix for non-IAM resource names, SSM paths, and the Project tag (e.g. loria-dora)."
  type        = string
}

variable "iam_name_prefix" {
  description = "Prefix for IAM roles and policies; the shared account requires cloudbatch818-."
  type        = string

  validation {
    condition     = startswith(var.iam_name_prefix, "cloudbatch818-")
    error_message = "IAM names in this account must start with \"cloudbatch818-\"."
  }
}

variable "github_oidc_sub_prefix" {
  description = "OIDC sub claim prefix for this repo (immutable form: repo:owner@id/repo@id)."
  type        = string

  validation {
    condition     = can(regex("^repo:[^@/]+@[0-9]+/[^@/]+@[0-9]+$", var.github_oidc_sub_prefix))
    error_message = "Expected the immutable form repo:<owner>@<owner-id>/<repo>@<repo-id>."
  }
}

variable "state_bucket" {
  description = "Terraform state bucket name. Created by scripts/bootstrap/ensure-state-bucket.sh before init, then imported here."
  type        = string
}
