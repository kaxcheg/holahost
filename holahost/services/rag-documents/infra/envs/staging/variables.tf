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
  description = "SNS subscription endpoint for the 5xx / p95-ingest alarms."
}

variable "ingestion_p95_budget_ms" {
  type    = number
  default = 20000 # INGESTION_P95_BUDGET
}

variable "search_p95_budget_ms" {
  type    = number
  default = 500 # SEARCH_P95_BUDGET
}

variable "success_rate_threshold_percent" {
  type        = number
  default     = 95 # operational placeholder — calibrate on real traffic
  description = "Alarm fires if ingest/search success rate drops below this, over evaluation_periods."
}

# Percentile and ratio metrics need enough raw data points per period to mean anything — a "p95"
# from one sample is not a percentile, it is that one number. The 10x gap between the ingest and
# search rate-limit ceilings (60/hr vs 600/hr per caller) says ingest is structurally the rarer of
# the two, so it gets the wider window. Both periods are reasoned rather than measured, and are
# meant to be calibrated once real traffic volume is known.
variable "ingest_metric_period_seconds" {
  type    = number
  default = 3600 # 1h — ingest is rare; needs a wide window to accumulate a meaningful sample
}

variable "search_metric_period_seconds" {
  type    = number
  default = 900 # 15m — search is more frequent than ingest but still low-volume right now
}
