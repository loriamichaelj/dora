output "state_bucket" {
  value = aws_s3_bucket.tfstate.bucket
}

output "ecr_repositories" {
  description = "Repository names; each environment's deploy role pushes (dev) or reads them."
  value       = { for k, repo in aws_ecr_repository.app : k => repo.name }
}

output "task_boundary_arn" {
  description = "Permissions boundary every infra/env task and task execution role must carry."
  value       = aws_iam_policy.task_boundary.arn
}

output "deploy_role_arns" {
  description = "Store each as the AWS_ROLE_ARN secret of the matching GitHub Environment."
  value = merge(
    { for env, role in aws_iam_role.env : env => role.arn },
    { shared = aws_iam_role.shared.arn },
  )
}
