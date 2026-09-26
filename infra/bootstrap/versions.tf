terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # Partial config; bootstrap.yml supplies bucket, key, and region via
  # -backend-config after ensuring the state bucket exists.
  backend "s3" {
    use_lockfile = true
    encrypt      = true
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.name_prefix
      Environment = "shared"
      ManagedBy   = "terraform"
      Stack       = "bootstrap"
    }
  }
}
