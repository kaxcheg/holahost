# Inputs the hosting app (Holahost) injects to place the lead-capture service into an environment.
# Env-invariant service config (secret keys, sizing) lives in ./config.yaml, not here.

variable "env" {
  type        = string
  description = "Target environment (staging | prod). Used in the SM secret path holahost/<env>/<key>."
}

variable "name_prefix" {
  type        = string
  description = "Resource name prefix, e.g. holahost-staging (Lambda names, log groups, SNS topic)."
}

variable "aws_region" {
  type        = string
  description = "Deploy region — injected as AWS_RESOURCES_REGION so the app reads secrets from its own region."
}

variable "image_uri" {
  type        = string
  description = "Container image URI (<ecr-url>:latest at bootstrap; CI mutates via update-function-code, ignored by lifecycle)."
}

variable "frontend_origin" {
  type        = string
  description = "The app URL that serves this service (https://<subdomain>), injected as FRONTEND_ORIGIN (CORS)."
}

variable "frontend_bucket" {
  type        = string
  description = "App frontend bucket NAME — injected as *_S3_BUCKET (the service reads its prompt/sample from it)."
}

variable "frontend_bucket_arn" {
  type        = string
  description = "App frontend bucket ARN — the exec role reads the sample guidebook + system-prompt/* from it."
}

variable "sample_guidebook_key" {
  type        = string
  description = "S3 key of the published sample guidebook (SAMPLE_GUIDEBOOK_S3_KEY + s3:GetObject scope)."
}

variable "system_prompt_key" {
  type        = string
  description = "Per-env S3 key of the private system prompt (SYSTEM_PROMPT_S3_KEY, read at cold start)."
}

variable "magic_link_path" {
  type        = string
  description = "Frontend-owned magic-link landing path (MAGIC_LINK_PATH); relayed to build the email link."
}

variable "magic_link_url_param" {
  type        = string
  description = "Frontend-owned magic-link token query-param name (MAGIC_LINK_URL_PARAM)."
}

variable "backend_env" {
  type        = map(string)
  description = "Parsed per-env backend config (<env>.env). Secret keys + blanks are dropped before use."
}

variable "recovery_window_in_days" {
  type        = number
  description = "Secrets Manager recovery window (staging 0, prod 30)."
}

variable "log_retention_days" {
  type        = number
  description = "CloudWatch log retention for the api + cleanup Lambdas."
}

variable "lambda_api_memory_mb" {
  type        = number
  description = "Request Lambda memory (MB)."
}

variable "lambda_api_timeout_s" {
  type        = number
  description = "Request Lambda timeout (s)."
}

variable "lambda_cleanup_memory_mb" {
  type        = number
  description = "Cleanup Lambda memory (MB)."
}

variable "lambda_cleanup_timeout_s" {
  type        = number
  description = "Cleanup Lambda timeout (s)."
}

variable "alert_email" {
  type        = string
  description = "SNS alarm subscription address for this service's observability topic."
}
