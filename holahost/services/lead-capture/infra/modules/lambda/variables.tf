variable "name_prefix" {
  type        = string
  description = "Env resource prefix, e.g. holahost-staging."
}

variable "image_uri" {
  type        = string
  description = "Container image URI for both functions (<ecr-url>:latest at bootstrap; CI mutates the running image via update-function-code, ignored via lifecycle)."
}

variable "environment_variables" {
  type        = map(string)
  description = "Non-secret Lambda env (parsed from <env>.env minus SM secrets, merged with config.yaml/s3_frontend/fe-env cross-source values, §10.9). Secrets are NOT here — loaded from SM at cold start (§10.3)."
}

variable "secret_arns" {
  type        = list(string)
  description = "SM secret ARNs the exec role may GetSecretValue (values(module.sm.secret_arns) — exactly the four keys, D-04)."
}

variable "frontend_bucket_arn" {
  type        = string
  description = "Frontend bucket ARN; the exec role reads the sample guidebook + system-prompt/* from it."
}

variable "sample_guidebook_key" {
  type        = string
  description = "S3 object key of the sample guidebook (config.yaml sample_guidebook_key) — the exec role gets s3:GetObject on it. Single source, no hardcoded literal (matches SAMPLE_GUIDEBOOK_S3_KEY)."
}

variable "api_memory_mb" {
  type        = number
  description = "Memory for the api function (config.yaml lambda_api_memory_mb)."
}

variable "api_timeout_s" {
  type        = number
  description = "Timeout for the api function (config.yaml lambda_api_timeout_s)."
}

variable "cleanup_memory_mb" {
  type        = number
  description = "Memory for the cleanup function (config.yaml lambda_cleanup_memory_mb)."
}

variable "cleanup_timeout_s" {
  type        = number
  description = "Timeout for the cleanup function (config.yaml lambda_cleanup_timeout_s)."
}

variable "log_retention_days" {
  type        = number
  description = "CloudWatch log retention for both functions (config.yaml log_retention_days)."
}
