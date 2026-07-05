variable "repository_name" {
  type        = string
  description = "ECR repository name (supplied from infra/config.yaml, e.g. holahost-api). Single repo shared by staging + prod (§13.5)."
}
