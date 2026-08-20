variable "env" {
  type    = string
  default = "prod"
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "alert_email" {
  type        = string
  description = "SNS subscription endpoint for the 5xx / p95-ingest alarms."
}

variable "ingestion_p95_budget_ms" {
  type    = number
  default = 20000 # §3.7 INGESTION_P95_BUDGET
}

variable "search_p95_budget_ms" {
  type    = number
  default = 500 # §3.7 SEARCH_P95_BUDGET
}

variable "success_rate_threshold_percent" {
  type        = number
  default     = 95 # TODO: no spec-defined threshold exists for this — operational placeholder, calibrate on real traffic
  description = "Alarm fires if ingest/search success rate drops below this, over evaluation_periods."
}

# Percentile/ratio metrics need enough raw data points per period to mean anything — a "p95" from
# 1 sample isn't a percentile, it's just that one number. RATE_LIMIT_INGEST (60/hr/client) vs
# RATE_LIMIT_DEFAULT for search (600/hr/client) — a 10x ceiling gap — signals ingest is
# structurally much rarer than search; with one caller at this early stage, actual volume is very
# likely far below even these ceilings. TODO: both are reasoned placeholders, not measured —
# calibrate once real traffic volume is known.
variable "ingest_metric_period_seconds" {
  type    = number
  default = 3600 # 1h — ingest is rare; needs a wide window to accumulate a meaningful sample
}

variable "search_metric_period_seconds" {
  type    = number
  default = 900 # 15m — search is more frequent than ingest but still low-volume right now
}
