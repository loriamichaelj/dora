# The environment's secrets (docs/CLOUD-DEVOPS-DESIGN.md §6.6):
#
#   <prefix>/<env>/db-owner        {"username": "dora_owner", "password": ...}  migrations
#   <prefix>/<env>/db-app          {"username": "dora_app", "password": ...}    the API, seed
#   <prefix>/<env>/ingest-api-key  a plain string                               the API
#
# Values come from ephemeral random passwords written through write-only
# arguments, so they're in neither the plan nor the state (C7). They're written
# once: bumping secret_string_wo_version is how a value would be replaced, and
# rotation is deferred (§11). db/bootstrap.sql creates the database roles with
# these passwords on the first deploy.

locals {
  secrets = {
    db-owner       = "Password of dora_owner, the role that runs migrations."
    db-app         = "Password of dora_app, the role the API and seed run as."
    ingest-api-key = "Key that pipelines send to the tracker's ingest API."
  }
}

resource "aws_secretsmanager_secret" "this" {
  for_each = local.secrets

  name                    = "${local.n}/${local.env}/${each.key}"
  description             = each.value
  recovery_window_in_days = var.secret_recovery_days
}

# Alphanumeric: they go into psql variables and connection settings unquoted.
# 32 characters of [A-Za-z0-9] is ~190 bits; the ingest key must be >= 32.
ephemeral "random_password" "db_owner" {
  length  = 32
  special = false
}

ephemeral "random_password" "db_app" {
  length  = 32
  special = false
}

ephemeral "random_password" "ingest_api_key" {
  length  = 48
  special = false
}

resource "aws_secretsmanager_secret_version" "db_owner" {
  secret_id = aws_secretsmanager_secret.this["db-owner"].id
  secret_string_wo = jsonencode({
    username = "dora_owner"
    password = ephemeral.random_password.db_owner.result
  })
  secret_string_wo_version = 1
}

resource "aws_secretsmanager_secret_version" "db_app" {
  secret_id = aws_secretsmanager_secret.this["db-app"].id
  secret_string_wo = jsonencode({
    username = "dora_app"
    password = ephemeral.random_password.db_app.result
  })
  secret_string_wo_version = 1
}

resource "aws_secretsmanager_secret_version" "ingest_api_key" {
  secret_id                = aws_secretsmanager_secret.this["ingest-api-key"].id
  secret_string_wo         = ephemeral.random_password.ingest_api_key.result
  secret_string_wo_version = 1
}
