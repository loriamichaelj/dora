# aws_region and name_prefix come from infra/project.env via TF_VAR_* (set by
# terraform.yml), so they have no defaults here.

variable "aws_region" {
  type = string
}

variable "name_prefix" {
  description = "Prefix for resource names and the Project tag (e.g. loria-dora)."
  type        = string
}

variable "vpc_cidr" {
  description = "Dora's own VPC; doesn't overlap Beacon's 10.0.0.0/16, in case they're ever peered."
  type        = string
  default     = "10.1.0.0/16"
}
