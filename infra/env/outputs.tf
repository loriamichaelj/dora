output "alb_url" {
  description = "Where this environment is served (HTTP until DNS lands, §6.10)."
  value       = "http://${aws_lb.this.dns_name}"
}

output "cluster" {
  value = aws_ecs_cluster.this.name
}

output "service" {
  value = aws_ecs_service.app.name
}

output "db_endpoint" {
  value = aws_db_instance.this.address
}

output "db_engine_version" {
  description = "The PostgreSQL 18.x RDS chose (open item 3)."
  value       = aws_db_instance.this.engine_version_actual
}

output "deploy_config_parameter" {
  value = aws_ssm_parameter.deploy_config.name
}
