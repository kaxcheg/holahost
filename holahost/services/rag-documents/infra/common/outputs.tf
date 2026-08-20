output "repository_url" {
  value       = aws_ecr_repository.this.repository_url
  description = "Consumed by infra/envs and the deploy/promote pipelines to build image URIs."
}
