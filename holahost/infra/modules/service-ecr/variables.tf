variable "service_name" {
  type        = string
  description = "The service's `<svc>` name — also its container name on `backbone` and its API path segment."
}

variable "keep_sha_images" {
  type        = number
  default     = 50
  description = "How many `git-<sha>` images to retain."
}

variable "keep_untagged_images" {
  type        = number
  default     = 30
  description = "How many untagged images to retain."
}
