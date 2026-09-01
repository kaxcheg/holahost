# The observability every Holahost service gets from the platform's completion event, and
# nothing beyond it.
#
# What is here is exactly what `holahost-observability`'s CORE_LOG_FIELDS make possible
# without knowing anything about a service: `op_completed` is one event name across the
# platform, `outcome` carries a failure's identity, and `duration_ms` is always present.
# Filters over those three are the same behind every service, so they are written once.
#
# What is deliberately NOT here is every metric that needs to know a route or a domain
# field — per-route latency, a success ratio, `chunk_count`, `top_score`. Those stay in the
# service's own root, where the route names they match on are visible next to the code that
# emits them. A module that took them as a map of filter definitions would be a wrapper
# around `aws_cloudwatch_log_metric_filter` rather than an abstraction over anything.
#
# The literals below are a contract, copied: an error class renamed in a service and not
# here silently stops matching, and `treat_missing_data = "notBreaching"` then reads the
# dead metric as health. `RateLimitExceededError` is `holahost-http`'s own and changes only
# with the library.

locals {
  namespace = "${var.metric_namespace_prefix}/${var.env}"
  prefix    = "${var.service_name}-${var.env}"
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/holahost/${var.env}/${var.service_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_sns_topic" "alerts" {
  name = "${local.prefix}-alerts"
}

resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# ---- The service failed ---------------------------------------------------------------
# `InternalError` is the platform's out-of-contract identity; `5*` catches a bare numeric
# status logged by the handler that answers a framework-level failure.

resource "aws_cloudwatch_log_metric_filter" "http_5xx" {
  name           = "${local.prefix}-5xx"
  log_group_name = aws_cloudwatch_log_group.app.name
  pattern        = "{ $.event = \"op_completed\" && ($.outcome = \"InternalError\" || $.outcome = \"5*\") }"

  metric_transformation {
    name      = "Http5xxCount"
    namespace = local.namespace
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "http_5xx" {
  alarm_name          = "${local.prefix}-5xx"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = aws_cloudwatch_log_metric_filter.http_5xx.metric_transformation[0].name
  namespace           = aws_cloudwatch_log_metric_filter.http_5xx.metric_transformation[0].namespace
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Any op_completed event with a 5xx outcome."
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"
}

# ---- The caller was refused ------------------------------------------------------------
# No alarm on either: both are ordinary at some rate, and what makes them interesting is a
# change in that rate rather than a threshold. They exist so the question can be asked.

resource "aws_cloudwatch_log_metric_filter" "auth_failures" {
  name           = "${local.prefix}-auth-failures"
  log_group_name = aws_cloudwatch_log_group.app.name
  # `403` never fires in a service whose foreign resources answer 404, but matching it
  # anyway keeps this the same filter behind every service.
  pattern = "{ $.event = \"op_completed\" && ($.outcome = \"401\" || $.outcome = \"403\") }"

  metric_transformation {
    name      = "AuthFailureCount"
    namespace = local.namespace
    value     = "1"
  }
}

resource "aws_cloudwatch_log_metric_filter" "rate_limit_failures" {
  name           = "${local.prefix}-rate-limit-failures"
  log_group_name = aws_cloudwatch_log_group.app.name
  pattern        = "{ $.event = \"op_completed\" && $.outcome = \"RateLimitExceededError\" }"

  metric_transformation {
    name      = "RateLimitFailureCount"
    namespace = local.namespace
    value     = "1"
  }
}

# A service's secrets are NOT here, deliberately. They are five lines of
# `aws_secretsmanager_secret` in the service's own environment root: a module block calling
# them would cost what it saved, the recovery window differs per environment anyway, and the
# one thing centralising them would buy — the `holahost/<env>/<svc>/<name>` convention in a
# single place — is not on offer, because `scripts/bootstrap.py` builds that same id
# independently in Python. Secrets in a module named for observability would only mean the
# next unrelated resource lands here too.
