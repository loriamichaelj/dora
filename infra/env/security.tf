# Security groups: the isolation boundary between environments in the shared
# VPC (docs/CLOUD-DEVOPS-DESIGN.md §6.3). Tier-to-tier rules reference security
# group IDs, never CIDRs. Nothing opens port 8000 (api) or 22.
#
#   internet --80--> alb --8080--> task (web -> api on 127.0.0.1) --5432--> db
#                                  task --443--> VPC endpoints, S3 (gateway)
#
# Rules are separate aws_security_group_rule resources: the ALB and task groups
# reference each other, which inline rules can't express without a cycle. They
# carry no tags, which the deploy role couldn't set on rules anyway.

resource "aws_security_group" "alb" {
  name        = "${local.base}-alb"
  description = "${local.env} ALB: HTTP from the internet"
  vpc_id      = local.vpc_id
  tags        = { Name = "${local.base}-alb" }
}

resource "aws_security_group" "task" {
  name        = "${local.base}-task"
  description = "${local.env} ECS tasks, including one-off tasks: HTTP from the ALB only"
  vpc_id      = local.vpc_id
  tags        = { Name = "${local.base}-task" }
}

resource "aws_security_group" "db" {
  name        = "${local.base}-db"
  description = "${local.env} RDS: PostgreSQL from this environment tasks only"
  vpc_id      = local.vpc_id
  tags        = { Name = "${local.base}-db" }
}

# --- ALB ----------------------------------------------------------------------

resource "aws_security_group_rule" "alb_in_http" {
  security_group_id = aws_security_group.alb.id
  type              = "ingress"
  description       = "HTTP from the internet (443 once DNS lands)"
  from_port         = 80
  to_port           = 80
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
}

resource "aws_security_group_rule" "alb_out_web" {
  security_group_id        = aws_security_group.alb.id
  type                     = "egress"
  description              = "HTTP to the web container of this environment tasks"
  from_port                = 8080
  to_port                  = 8080
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.task.id
}

# --- Tasks --------------------------------------------------------------------

resource "aws_security_group_rule" "task_in_alb" {
  security_group_id        = aws_security_group.task.id
  type                     = "ingress"
  description              = "HTTP from this environment ALB, to web"
  from_port                = 8080
  to_port                  = 8080
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.alb.id
}

resource "aws_security_group_rule" "task_out_db" {
  security_group_id        = aws_security_group.task.id
  type                     = "egress"
  description              = "PostgreSQL to this environment database"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.db.id
}

# Private subnets have no internet route: HTTPS reaches only the interface
# endpoints (ECR, Logs, Secrets Manager), in the VPC, and S3 through its
# gateway endpoint, for image layers.
resource "aws_security_group_rule" "task_out_endpoints" {
  security_group_id = aws_security_group.task.id
  type              = "egress"
  description       = "HTTPS to the VPC interface endpoints"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = [local.vpc_cidr]
}

# The S3 gateway endpoint's prefix list, read from the endpoint itself: looking
# the list up directly needs ec2:GetManagedPrefixListEntries, which the deploy
# role doesn't have.
data "aws_vpc_endpoint" "s3" {
  vpc_id       = local.vpc_id
  service_name = "com.amazonaws.${var.aws_region}.s3"
}

resource "aws_security_group_rule" "task_out_s3" {
  security_group_id = aws_security_group.task.id
  type              = "egress"
  description       = "HTTPS to S3 through the gateway endpoint (ECR image layers)"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  prefix_list_ids   = [data.aws_vpc_endpoint.s3.prefix_list_id]
}

# --- Database -----------------------------------------------------------------

resource "aws_security_group_rule" "db_in_task" {
  security_group_id        = aws_security_group.db.id
  type                     = "ingress"
  description              = "PostgreSQL from this environment tasks"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.task.id
}
