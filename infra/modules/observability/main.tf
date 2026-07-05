# Observability contour (§10.5): metric filters over the two Lambda log groups (created by the
# lambda module, I-12), four alarms (§10.2 SLO budgets + §10.5), one SNS topic with the single-host
# email subscription (C-03). Metrics store RAW values (request_duration_ms,
# sample_budget_tokens_used); p95 / daily-sum live in the alarm statistic, not the metric name (C-09).
locals {
  namespace = var.name_prefix

  # SLO thresholds are spec constants (§10.2), not config — same pattern as the CSP values in the
  # cloudfront module (§10.9 "module constants").
  response_p95_threshold_ms  = 8000  # RESPONSE_P95_BUDGET = 8s
  ingestion_p95_threshold_ms = 60000 # INGESTION_P95_BUDGET = 60s
  sample_budget_alarm_factor = 0.8   # alarm at 0.8 x SAMPLE_BUDGET_DAILY_CAP (§10.5)
}

resource "aws_sns_topic" "alarms" {
  name = "${var.name_prefix}-alarms"
}

resource "aws_sns_topic_subscription" "alert_email" {
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# --- metric filters: api log group (§10.5) ---

resource "aws_cloudwatch_log_metric_filter" "request_count" {
  name           = "${var.name_prefix}-request-count"
  log_group_name = var.api_log_group_name
  pattern        = "{ $.event = \"http_request_completed\" }"

  metric_transformation {
    name      = "request_count"
    namespace = local.namespace
    value     = "1"
    dimensions = {
      endpoint = "$.endpoint"
      status   = "$.status"
    }
  }
}

resource "aws_cloudwatch_log_metric_filter" "request_duration_ms" {
  name           = "${var.name_prefix}-request-duration-ms"
  log_group_name = var.api_log_group_name
  pattern        = "{ $.event = \"http_request_completed\" }"

  metric_transformation {
    name      = "request_duration_ms"
    namespace = local.namespace
    value     = "$.duration_ms"
    unit      = "Milliseconds"
    dimensions = {
      endpoint = "$.endpoint"
    }
  }
}

resource "aws_cloudwatch_log_metric_filter" "error_count" {
  name           = "${var.name_prefix}-error-count"
  log_group_name = var.api_log_group_name
  pattern        = "{ $.event = \"http_request_completed\" && $.level = \"ERROR\" }"

  metric_transformation {
    name      = "error_count"
    namespace = local.namespace
    value     = "1"
    dimensions = {
      code = "$.error_code"
    }
  }
}

resource "aws_cloudwatch_log_metric_filter" "sample_budget_tokens" {
  name           = "${var.name_prefix}-sample-budget-tokens"
  log_group_name = var.api_log_group_name
  pattern        = "{ $.event = \"sample_response_completed\" }"

  metric_transformation {
    name      = "sample_budget_tokens_used"
    namespace = local.namespace
    value     = "$.sample_tokens_used"
  }
}

# --- metric filters: cleanup log group (§10.5) ---

resource "aws_cloudwatch_log_metric_filter" "cleanup_counters" {
  for_each = {
    cleanup_deleted_guidebooks   = "$.deleted_guidebooks"
    cleanup_expired_magic_links  = "$.expired_magic_links"
    cleanup_deleted_rate_windows = "$.deleted_rate_windows"
  }

  name           = "${var.name_prefix}-${replace(each.key, "_", "-")}"
  log_group_name = var.cleanup_log_group_name
  pattern        = "{ $.event = \"cleanup_completed\" }"

  metric_transformation {
    name      = each.key
    namespace = local.namespace
    value     = each.value
  }
}

# --- alarms (§10.2 / §10.5); alarm dimensions must exactly match the published metric's set ---

resource "aws_cloudwatch_metric_alarm" "response_p95" {
  alarm_name          = "${var.name_prefix}-response-p95"
  alarm_description   = "p95(/api/generate duration_ms) over 15 min above RESPONSE_P95_BUDGET (§10.2)."
  namespace           = local.namespace
  metric_name         = "request_duration_ms"
  dimensions          = { endpoint = "/api/generate" }
  extended_statistic  = "p95"
  period              = 900
  evaluation_periods  = 1
  threshold           = local.response_p95_threshold_ms
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "ingestion_p95" {
  alarm_name          = "${var.name_prefix}-ingestion-p95"
  alarm_description   = "p95(/api/ingest/upload duration_ms) over 15 min above INGESTION_P95_BUDGET (§10.2)."
  namespace           = local.namespace
  metric_name         = "request_duration_ms"
  dimensions          = { endpoint = "/api/ingest/upload" }
  extended_statistic  = "p95"
  period              = 900
  evaluation_periods  = 1
  threshold           = local.ingestion_p95_threshold_ms
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "internal_errors" {
  alarm_name          = "${var.name_prefix}-internal-errors"
  alarm_description   = "Any unhandled ERR_INTERNAL within 5 min (§10.5; threshold — clarification C-04)."
  namespace           = local.namespace
  metric_name         = "error_count"
  dimensions          = { code = "ERR_INTERNAL" }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "sample_budget" {
  alarm_name          = "${var.name_prefix}-sample-budget"
  alarm_description   = "Daily sample output-token spend above 0.8 x SAMPLE_BUDGET_DAILY_CAP (§10.5)."
  namespace           = local.namespace
  metric_name         = "sample_budget_tokens_used"
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = local.sample_budget_alarm_factor * var.sample_budget_daily_cap_tokens
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}
