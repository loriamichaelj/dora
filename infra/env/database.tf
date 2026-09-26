# RDS for PostgreSQL 18 (docs/CLOUD-DEVOPS-DESIGN.md §6.6): private, reachable
# only from this environment's task security group, TLS required.
#
# The master user's password is generated and stored by RDS in Secrets Manager
# (manage_master_user_password), so it never appears in Terraform state (C7).
# Only the db-bootstrap task can read it (iam.tf).

resource "aws_db_subnet_group" "this" {
  name       = "${local.base}-db"
  subnet_ids = local.private_subnet_ids
}

resource "aws_db_parameter_group" "this" {
  name   = "${local.base}-pg18"
  family = "postgres18"

  # Reject plaintext connections; the tasks connect with verify-full.
  # apply_method matches what RDS reports back; the provider's default
  # ("immediate") would show as a change on every plan.
  parameter {
    name         = "rds.force_ssl"
    value        = "1"
    apply_method = "pending-reboot"
  }
}

resource "aws_db_instance" "this" {
  identifier = "${local.base}-db"
  engine     = "postgres"
  # 18 is required for uuidv7() (Phase A D11). Major version only: RDS picks
  # its current 18.x and applies minor upgrades itself (open item 3).
  engine_version = "18"
  instance_class = var.db_instance_class

  db_name                     = "dora"
  username                    = "dora_admin"
  manage_master_user_password = true
  port                        = 5432

  allocated_storage = var.db_allocated_storage_gb
  storage_type      = "gp3"
  storage_encrypted = true

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.db.id]
  parameter_group_name   = aws_db_parameter_group.this.name
  publicly_accessible    = false
  multi_az               = var.db_multi_az
  ca_cert_identifier     = "rds-ca-rsa2048-g1" # in the RDS bundle baked into the images

  backup_retention_period    = var.db_backup_retention_days
  copy_tags_to_snapshot      = true
  deletion_protection        = var.db_deletion_protection
  skip_final_snapshot        = var.db_skip_final_snapshot
  final_snapshot_identifier  = var.db_skip_final_snapshot ? null : "${local.base}-db-final"
  auto_minor_version_upgrade = true
  apply_immediately          = local.env == "dev"
}
