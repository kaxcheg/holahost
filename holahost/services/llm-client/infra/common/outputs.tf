output "repository_url" {
  value       = module.ecr.repository_url
  description = "Consumed by infra/envs and the deploy/promote pipelines to build image URIs."
}
