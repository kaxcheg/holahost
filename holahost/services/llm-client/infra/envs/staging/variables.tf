variable "env" {
  type    = string
  default = "staging"
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "log_retention_days" {
  type    = number
  default = 14
}

variable "alert_email" {
  type        = string
  description = "SNS subscription endpoint for this service's alarms."
}

# ---- Alarm thresholds (observability.tf) -----------------------------------------------------

variable "metric_period_seconds" {
  type        = number
  default     = 900
  description = "The window of the generation alarms: long enough that one slow call is not a p95."
}

variable "generation_p95_budget_ms" {
  type        = number
  default     = 15000
  description = "GENERATION_P95_BUDGET: the path with no retries."
}

variable "success_rate_threshold_percent" {
  type    = number
  default = 90
}

variable "upstream_share_threshold_percent" {
  type        = number
  default     = 20
  description = "Share of generations answered UpstreamLlmError, over two windows in a row."
}

variable "downgraded_share_threshold_percent" {
  type        = number
  default     = 10
  description = "Share of successful generations served by a downgrade target."
}

variable "downgraded_period_seconds" {
  type        = number
  default     = 3600
  description = "Downgrades are a policy, not a fault: judged over an hour, not a burst."
}

variable "budget_alarm_percent" {
  type        = number
  default     = 80
  description = "Warn when a provider's daily spend reaches this share of its ceiling (BUDGET_CAP_PROVIDER_* in .env)."
}

variable "rate_min_requests" {
  type        = number
  default     = 5
  description = "Below this many generations in a window a success rate is not judged: one failure of one request is not a rate."
}
