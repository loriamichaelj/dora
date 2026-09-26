# Dora's VPC, shared by its environments (docs/CLOUD-DEVOPS-DESIGN.md §6.2, C10).
#
# Public subnets hold only ALBs. Private subnets (ECS tasks, RDS) have no route
# to the internet: no NAT gateway. Tasks reach AWS through VPC endpoints only,
# whose interfaces live in dedicated shared subnets. Isolation between
# environments is by security group (§6.3), not by subnet or routing.

data "aws_availability_zones" "available" {
  state = "available"

  filter {
    name   = "opt-in-status"
    values = ["opt-in-not-required"]
  }

  # Fargate isn't offered in use1-az3.
  exclude_zone_ids = ["use1-az3"]
}

locals {
  n = var.name_prefix

  # Two AZs: the ALB requires at least two.
  azs = slice(sort(data.aws_availability_zones.available.names), 0, 2)

  # Third octet of each /24, per environment and tier; list position = AZ index.
  # Only dev exists (C14). Reserved for later, not created:
  #   stage: public 2, 3; private 12, 13
  #   prod:  public 4, 5; private 14, 15
  layout = {
    dev = { public = [0, 1], private = [10, 11] }
  }
  endpoint_octets = [20, 21]

  subnets = merge(
    {
      for s in flatten([
        for env, tiers in local.layout : [
          for tier, octets in tiers : [
            for i, octet in octets : { key = "${env}-${tier}-${i}", scope = env, tier = tier, i = i, octet = octet }
          ]
        ]
      ]) : s.key => s
    },
    {
      for i, octet in local.endpoint_octets :
      "shared-endpoints-${i}" => { key = "shared-endpoints-${i}", scope = "shared", tier = "endpoints", i = i, octet = octet }
    },
  )

  # Everything a Fargate task needs with no internet route (platform 1.4+):
  # pull images (ecr.api, ecr.dkr, plus S3 for layers), ship logs, and
  # receive secrets. No ssm/ssmmessages: nothing at runtime reads SSM, and
  # ECS Exec is deferred.
  interface_endpoints = toset(["ecr.api", "ecr.dkr", "logs", "secretsmanager"])
}

resource "aws_vpc" "this" {
  cidr_block = var.vpc_cidr

  # Both required for the interface endpoints' private DNS names.
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "${local.n}-vpc" }
}

resource "aws_subnet" "this" {
  for_each = local.subnets

  vpc_id            = aws_vpc.this.id
  availability_zone = local.azs[each.value.i]
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, each.value.octet)

  # Nothing gets a public IP by default, including in public subnets:
  # only ALBs live there, and they manage their own addresses.
  map_public_ip_on_launch = false

  tags = {
    Name  = "${local.n}-${each.value.scope}-${each.value.tier}-${substr(local.azs[each.value.i], -1, 1)}"
    Scope = each.value.scope # which environment the subnet serves; Environment stays "shared"
    Tier  = each.value.tier
  }
}

# --- Internet access: public subnets only -----------------------------------

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${local.n}-igw" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${local.n}-public" }
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this.id
}

resource "aws_route_table_association" "public" {
  for_each = { for k, s in local.subnets : k => s if s.tier == "public" }

  subnet_id      = aws_subnet.this[each.key].id
  route_table_id = aws_route_table.public.id
}

# --- Private subnets: no default route; S3 via the gateway endpoint ---------

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${local.n}-private" }
}

resource "aws_route_table_association" "private" {
  for_each = { for k, s in local.subnets : k => s if s.tier != "public" }

  subnet_id      = aws_subnet.this[each.key].id
  route_table_id = aws_route_table.private.id
}

# --- VPC endpoints ------------------------------------------------------------

# Free. ECR serves image layers from S3.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]

  tags = { Name = "${local.n}-s3" }
}

# The one CIDR-based rule in the design (§6.2): endpoints are shared by every
# environment, so any address in the VPC may reach them.
resource "aws_security_group" "endpoints" {
  name        = "${local.n}-shared-endpoints"
  description = "Interface VPC endpoints: HTTPS from anywhere in the VPC"
  vpc_id      = aws_vpc.this.id

  ingress {
    description = "HTTPS from the VPC"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  tags = { Name = "${local.n}-shared-endpoints" }
}

resource "aws_vpc_endpoint" "interface" {
  for_each = local.interface_endpoints

  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.aws_region}.${each.key}"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [for k, s in local.subnets : aws_subnet.this[k].id if s.tier == "endpoints"]
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true

  tags = { Name = "${local.n}-${replace(each.key, ".", "-")}" }
}
