variable "env" {
  type        = string
  description = "Deployment environment (staging | prod)."
}

variable "name_prefix" {
  type        = string
  description = "Resource name prefix, e.g. holahost-prod."
}

variable "aws_region" {
  type        = string
  description = "AWS region for the default provider (deploy region), e.g. us-east-1."
}
