# Set by terraform.yml: aws_region, name_prefix, iam_name_prefix (from
# infra/project.env), state_bucket, and environment. Everything else comes from
# environments/<environment>.tfvars.

variable "aws_region" {
  type = string
}

variable "name_prefix" {
  description = "Prefix for resource names, SSM paths, secrets, log groups, and the Project tag (e.g. loria-dora)."
  type        = string
}

variable "iam_name_prefix" {
  description = "Prefix for IAM names; the shared account requires cloudbatch818-."
  type        = string
}

variable "state_bucket" {
  description = "Terraform state bucket, for reading the shared network's outputs."
  type        = string
}

variable "environment" {
  type = string

  validation {
    condition     = contains(["dev", "stage", "prod"], var.environment)
    error_message = "environment must be dev, stage, or prod."
  }
}

# --- ECS ------------------------------------------------------------------------

variable "app_cpu" {
  description = "CPU units for the whole app task (api + web), e.g. 512 = 0.5 vCPU."
  type        = number
}

variable "app_memory" {
  description = "Memory (MiB) for the whole app task."
  type        = number
}

variable "app_desired_count" {
  description = "Tasks the first deploy scales the service to; Terraform creates it with 0 (§7.4)."
  type        = number
}

# --- Database -------------------------------------------------------------------

variable "db_instance_class" {
  type = string
}

variable "db_allocated_storage_gb" {
  type = number
}

variable "db_multi_az" {
  type = bool
}

variable "db_backup_retention_days" {
  type = number
}

variable "db_deletion_protection" {
  type = bool
}

variable "db_skip_final_snapshot" {
  description = "true only where the data is disposable (dev)."
  type        = bool
}

# --- Other ----------------------------------------------------------------------

variable "alb_deletion_protection" {
  type = bool
}

variable "log_retention_days" {
  type = number
}

variable "secret_recovery_days" {
  description = "Days a deleted secret can be restored. 0 in dev, so a torn-down environment can be rebuilt at once with the same secret names (B8)."
  type        = number
}
