variable "name_prefix" {
  type        = string
  description = "Env resource prefix (holahost-<env>); doubles as the custom CloudWatch metric namespace."
}

variable "api_log_group_name" {
  type        = string
  description = "API Lambda log group (created by the lambda module) the api metric filters read."
}

variable "cleanup_log_group_name" {
  type        = string
  description = "Cleanup Lambda log group (created by the lambda module) the cleanup filters read."
}

variable "alert_email" {
  type        = string
  description = "Alarm notification address (config.yaml alert_email); the email subscription needs a manual confirm after apply (runbook)."
}

variable "sample_budget_daily_cap_tokens" {
  type        = number
  description = "Daily sample output-token cap; single source is <env>.env SAMPLE_BUDGET_DAILY_CAP_TOKENS (§10.9). The alarm fires at 0.8 x this value (§10.5)."
}
