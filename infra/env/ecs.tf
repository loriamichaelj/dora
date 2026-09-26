# ECS on Fargate (docs/CLOUD-DEVOPS-DESIGN.md §6.4): one cluster per
# environment, one service whose tasks run web and api side by side.
#
# Terraform creates the service at 0 tasks, on a placeholder task definition,
# and then leaves the task definition and desired count to deploy.yml (§7.4,
# C3). Starting at zero avoids first-deploy churn: nothing runs until a real
# release is rolled out.

resource "aws_ecs_cluster" "this" {
  name = local.base

  # Container Insights costs money per metric; deferred (§6.9, §11).
  setting {
    name  = "containerInsights"
    value = "disabled"
  }
}

# Only exists so the service can be created with its load balancer wired to
# web:8080 before any release exists. Never runs (desired count 0), and deploys
# register the real app family instead (deploy/ecs/app.json.tmpl).
resource "aws_ecs_task_definition" "placeholder" {
  family                   = "${local.base}-placeholder"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"

  runtime_platform {
    cpu_architecture        = "ARM64"
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([
    {
      name         = "web"
      image        = "public.ecr.aws/nginx/nginx:stable-alpine"
      essential    = true
      portMappings = [{ containerPort = 8080, protocol = "tcp" }]
    }
  ])
}

resource "aws_ecs_service" "app" {
  name             = "${local.base}-app"
  cluster          = aws_ecs_cluster.this.id
  task_definition  = aws_ecs_task_definition.placeholder.arn
  desired_count    = 0
  launch_type      = "FARGATE"
  platform_version = "LATEST"

  network_configuration {
    subnets          = local.private_subnet_ids
    security_groups  = [aws_security_group.task.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.web.arn
    container_name   = "web"
    container_port   = 8080
  }

  # Rolling: keep every healthy task until its replacement is healthy.
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = 60

  # If new tasks never become healthy, ECS rolls back by itself (§6.4).
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  enable_ecs_managed_tags = true
  propagate_tags          = "SERVICE"
  wait_for_steady_state   = false

  lifecycle {
    ignore_changes = [task_definition, desired_count]
  }

  # The listener must exist before a service can register targets.
  depends_on = [aws_lb_listener.http]
}
