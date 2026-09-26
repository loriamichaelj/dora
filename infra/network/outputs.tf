# Read by infra/env via terraform_remote_state (env:/shared/network.tfstate).

output "vpc_id" {
  value = aws_vpc.this.id
}

output "vpc_cidr" {
  value = aws_vpc.this.cidr_block
}

output "availability_zones" {
  value = local.azs
}

output "public_subnet_ids" {
  description = "Per environment, one public subnet per AZ (ALB placement)."
  value = {
    for env in keys(local.layout) :
    env => [for i in range(length(local.azs)) : aws_subnet.this["${env}-public-${i}"].id]
  }
}

output "private_subnet_ids" {
  description = "Per environment, one private subnet per AZ (ECS tasks and RDS)."
  value = {
    for env in keys(local.layout) :
    env => [for i in range(length(local.azs)) : aws_subnet.this["${env}-private-${i}"].id]
  }
}

output "endpoint_security_group_id" {
  value = aws_security_group.endpoints.id
}
