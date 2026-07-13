output "repository_url" {
  description = "ECR repo URL (CI pushes git-<sha>/release-v* tags; the lambda module reads it via data source for image_uri)."
  value       = aws_ecr_repository.api.repository_url
}

output "repository_arn" {
  description = "ECR repository ARN."
  value       = aws_ecr_repository.api.arn
}
