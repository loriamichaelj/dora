terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # Partial config; terraform.yml supplies bucket, key, and region via
  # -backend-config. Key: env:/shared/network.tfstate.
  backend "s3" {
    use_lockfile = true
    encrypt      = true
  }
}

provider "aws" {
  region = var.aws_region

  # Every network resource is Environment=shared: the shared deploy role may
  # only create and modify resources carrying these tags (infra/bootstrap/iam.tf).
  default_tags {
    tags = {
      Project     = var.name_prefix
      Environment = "shared"
      ManagedBy   = "terraform"
      Stack       = "network"
    }
  }
}
