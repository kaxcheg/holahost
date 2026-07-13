variable "repository_name" {
  type        = string
  description = "GitHub repository name (config.yaml project). The repo pre-exists and is IMPORTED into state (runbook), never created by Terraform."
}

variable "prod_reviewer_username" {
  type        = string
  description = "GitHub username whose approval gates prod deployments (config.yaml github_owner)."
}
