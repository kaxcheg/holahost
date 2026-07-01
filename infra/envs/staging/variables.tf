variable "env" {
  type        = string
  description = "Deployment environment (staging | prod)."
}

variable "name_prefix" {
  type        = string
  description = "Resource name prefix, e.g. holahost-staging."
}
