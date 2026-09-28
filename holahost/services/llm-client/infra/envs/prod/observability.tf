# This service's own metrics — everything that has to know the route or a domain field. The
# platform half (log group, alert topic, 5xx, auth failures, rate-limit refusals) comes from
# `module.platform`; these publish into its namespace and alarm through its topic.
#
# Every line of the generation route carries the same `route` — the resolved path — whether the
# route wrote it (success) or the platform's handlers did (a refusal): both are assembled by
# `holahost_http.log_completion`. One literal therefore counts every outcome.
#
# The literals below are a contract copied by hand: an error class renamed in the code and not
# here stops matching silently, and `treat_missing_data = "notBreaching"` then reads the dead
# metric as health.
#
# Counters feeding a ratio — an alarm's or a dashboard's — carry `default_value = 0`. A filter
# publishes a datapoint only for a line it matches; with the default, every other line ingested in
# the period publishes a 0, so a window with traffic but, say, no failures reads 0 rather than
# missing, and the ratio evaluates. A window with no lines at all still has no datapoints: these
# alarms then stay OK, so a container that stopped logging is not what they detect — nothing on
# the platform alarms on the absence of traffic yet.
#
# The success rate counts only what is the service's fault — `UpstreamLlmError` and
# `InternalError` against the successes — and is judged only from `var.rate_min_requests`
# generations in the window: a caller's expired token or oversized body is not degradation, and one
# failure of one request is not a rate.

locals {
  generate_route = "POST /api/llm-client/generate"
  on_generate    = "$.event = \"op_completed\" && $.route = \"${local.generate_route}\""
  succeeded      = "${local.on_generate} && $.outcome = \"success\""
  budget_caps = {
    input  = tonumber(local.settings["BUDGET_CAP_PROVIDER_INPUT_TOKENS"])
    output = tonumber(local.settings["BUDGET_CAP_PROVIDER_OUTPUT_TOKENS"])
  }
}

# ---- Volume and success rate --------------------------------------------------------------------

resource "aws_cloudwatch_log_metric_filter" "generate_requests" {
  name           = "llm-client-${var.env}-generate-requests"
  log_group_name = module.platform.log_group_name
  pattern        = "{ ${local.on_generate} }"

  metric_transformation {
    name          = "GenerateRequestCount"
    namespace     = module.platform.metric_namespace
    value         = "1"
    default_value = 0
  }
}

resource "aws_cloudwatch_log_metric_filter" "generate_success" {
  name           = "llm-client-${var.env}-generate-success"
  log_group_name = module.platform.log_group_name
  pattern        = "{ ${local.succeeded} }"

  metric_transformation {
    name          = "GenerateSuccessCount"
    namespace     = module.platform.metric_namespace
    value         = "1"
    default_value = 0
  }
}

resource "aws_cloudwatch_log_metric_filter" "internal_errors" {
  name           = "llm-client-${var.env}-internal-errors"
  log_group_name = module.platform.log_group_name
  pattern        = "{ ${local.on_generate} && $.outcome = \"InternalError\" }"

  metric_transformation {
    name          = "InternalErrorCount"
    namespace     = module.platform.metric_namespace
    value         = "1"
    default_value = 0
  }
}

resource "aws_cloudwatch_metric_alarm" "generate_success_rate" {
  alarm_name          = "llm-client-${var.env}-generate-success-rate"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 1
  threshold           = var.success_rate_threshold_percent
  alarm_description   = "Generation success rate, over what is the service's fault, dropped below the threshold."
  alarm_actions       = [module.platform.alerts_topic_arn]
  treat_missing_data  = "notBreaching"

  metric_query {
    id          = "rate"
    expression  = "IF((success+upstream+internal) >= ${var.rate_min_requests}, (success/(success+upstream+internal))*100, 100)"
    label       = "GenerateSuccessRate"
    return_data = true
  }
  metric_query {
    id = "success"
    metric {
      metric_name = aws_cloudwatch_log_metric_filter.generate_success.metric_transformation[0].name
      namespace   = module.platform.metric_namespace
      period      = var.metric_period_seconds
      stat        = "Sum"
    }
  }
  metric_query {
    id = "upstream"
    metric {
      metric_name = aws_cloudwatch_log_metric_filter.upstream_failures.metric_transformation[0].name
      namespace   = module.platform.metric_namespace
      period      = var.metric_period_seconds
      stat        = "Sum"
    }
  }
  metric_query {
    id = "internal"
    metric {
      metric_name = aws_cloudwatch_log_metric_filter.internal_errors.metric_transformation[0].name
      namespace   = module.platform.metric_namespace
      period      = var.metric_period_seconds
      stat        = "Sum"
    }
  }
}

# ---- Duration ----------------------------------------------------------------------------------
# p95 is computed at alarm time from the raw datapoints; `provider_ms` beside it shows how much of
# the time is the vendor's — growth in duration with `provider_ms` unchanged is a regression here.

resource "aws_cloudwatch_log_metric_filter" "generate_duration" {
  name           = "llm-client-${var.env}-generate-duration"
  log_group_name = module.platform.log_group_name
  pattern        = "{ ${local.succeeded} }"

  metric_transformation {
    name      = "GenerateDurationMs"
    namespace = module.platform.metric_namespace
    value     = "$.duration_ms"
    unit      = "Milliseconds"
  }
}

resource "aws_cloudwatch_metric_alarm" "generate_p95" {
  alarm_name          = "llm-client-${var.env}-generate-p95"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = aws_cloudwatch_log_metric_filter.generate_duration.metric_transformation[0].name
  namespace           = module.platform.metric_namespace
  period              = var.metric_period_seconds
  extended_statistic  = "p95"
  threshold           = var.generation_p95_budget_ms
  alarm_description   = "p95 generation duration exceeds GENERATION_P95_BUDGET."
  alarm_actions       = [module.platform.alerts_topic_arn]
  treat_missing_data  = "notBreaching"
}

resource "aws_cloudwatch_log_metric_filter" "provider_ms" {
  name           = "llm-client-${var.env}-provider-ms"
  log_group_name = module.platform.log_group_name
  pattern        = "{ ${local.succeeded} }"

  metric_transformation {
    name      = "ProviderMs"
    namespace = module.platform.metric_namespace
    value     = "$.provider_ms"
    unit      = "Milliseconds"
  }
}

# ---- The upstream -------------------------------------------------------------------------------

resource "aws_cloudwatch_log_metric_filter" "upstream_failures" {
  name           = "llm-client-${var.env}-upstream-failures"
  log_group_name = module.platform.log_group_name
  pattern        = "{ ${local.on_generate} && $.outcome = \"UpstreamLlmError\" }"

  metric_transformation {
    name          = "UpstreamFailureCount"
    namespace     = module.platform.metric_namespace
    value         = "1"
    default_value = 0
  }
}

resource "aws_cloudwatch_metric_alarm" "upstream_share" {
  alarm_name          = "llm-client-${var.env}-upstream-share"
  comparison_operator = "GreaterThanThreshold"
  # Two windows in a row: one vendor 529 among a handful of requests is not an outage.
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  threshold           = var.upstream_share_threshold_percent
  alarm_description   = "Share of generations whose every candidate failed transiently (UpstreamLlmError)."
  alarm_actions       = [module.platform.alerts_topic_arn]
  treat_missing_data  = "notBreaching"

  metric_query {
    id          = "share"
    expression  = "(upstream/requests)*100"
    label       = "UpstreamShare"
    return_data = true
  }
  metric_query {
    id = "upstream"
    metric {
      metric_name = aws_cloudwatch_log_metric_filter.upstream_failures.metric_transformation[0].name
      namespace   = module.platform.metric_namespace
      period      = var.metric_period_seconds
      stat        = "Sum"
    }
  }
  metric_query {
    id = "requests"
    metric {
      metric_name = aws_cloudwatch_log_metric_filter.generate_requests.metric_transformation[0].name
      namespace   = module.platform.metric_namespace
      period      = var.metric_period_seconds
      stat        = "Sum"
    }
  }
}

resource "aws_cloudwatch_log_metric_filter" "attempts" {
  name           = "llm-client-${var.env}-attempts"
  log_group_name = module.platform.log_group_name
  pattern        = "{ ${local.succeeded} }"

  metric_transformation {
    name      = "Attempts"
    namespace = module.platform.metric_namespace
    value     = "$.attempts"
  }
}

# Attempts cut off by the service's own timeout, on any line that carries the count — the success
# and `UpstreamLlmError`. Its sum estimates the spend that bypassed the usage log (B-12).
resource "aws_cloudwatch_log_metric_filter" "provider_timeouts" {
  name           = "llm-client-${var.env}-provider-timeouts"
  log_group_name = module.platform.log_group_name
  pattern        = "{ ${local.on_generate} && $.provider_timeouts >= 0 }"

  metric_transformation {
    name      = "ProviderTimeouts"
    namespace = module.platform.metric_namespace
    value     = "$.provider_timeouts"
  }
}

resource "aws_cloudwatch_log_metric_filter" "failed_over" {
  name           = "llm-client-${var.env}-failed-over"
  log_group_name = module.platform.log_group_name
  pattern        = "{ ${local.succeeded} && $.failed_over IS TRUE }"

  metric_transformation {
    name          = "FailedOverCount"
    namespace     = module.platform.metric_namespace
    value         = "1"
    default_value = 0
  }
}

# ---- Downgrades: the quiet loss of quality (B-4) ------------------------------------------------

resource "aws_cloudwatch_log_metric_filter" "downgraded" {
  name           = "llm-client-${var.env}-downgraded"
  log_group_name = module.platform.log_group_name
  pattern        = "{ ${local.succeeded} && $.downgraded IS TRUE }"

  metric_transformation {
    name          = "DowngradedCount"
    namespace     = module.platform.metric_namespace
    value         = "1"
    default_value = 0
  }
}

resource "aws_cloudwatch_metric_alarm" "downgraded_share" {
  alarm_name          = "llm-client-${var.env}-downgraded-share"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = var.downgraded_share_threshold_percent
  alarm_description   = "Callers are getting a cheaper model than they ask for, and cannot see it themselves."
  alarm_actions       = [module.platform.alerts_topic_arn]
  treat_missing_data  = "notBreaching"

  metric_query {
    id          = "share"
    expression  = "(downgraded/success)*100"
    label       = "DowngradedShare"
    return_data = true
  }
  metric_query {
    id = "downgraded"
    metric {
      metric_name = aws_cloudwatch_log_metric_filter.downgraded.metric_transformation[0].name
      namespace   = module.platform.metric_namespace
      period      = var.downgraded_period_seconds
      stat        = "Sum"
    }
  }
  metric_query {
    id = "success"
    metric {
      metric_name = aws_cloudwatch_log_metric_filter.generate_success.metric_transformation[0].name
      namespace   = module.platform.metric_namespace
      period      = var.downgraded_period_seconds
      stat        = "Sum"
    }
  }
}

# ---- Spend and the provider budgets --------------------------------------------------------------
# On every line that carries tokens: a success, a content refusal (charged too) and an unrecorded
# spend — not only `outcome = "success"`. Split by provider, a bounded dimension: the registry's.
# A metric with dimensions takes no `default_value`.

resource "aws_cloudwatch_log_metric_filter" "tokens" {
  for_each = { input = "input_tokens", output = "output_tokens" }

  name           = "llm-client-${var.env}-${each.key}-tokens"
  log_group_name = module.platform.log_group_name
  pattern        = "{ ${local.on_generate} && $.${each.value} >= 0 }"

  metric_transformation {
    name       = "${title(each.key)}Tokens"
    namespace  = module.platform.metric_namespace
    value      = "$.${each.value}"
    dimensions = { Provider = "$.provider" }
  }
}

# A warning before the provider ceiling refuses anyone: the day's spend (UTC-day periods, as the
# service's own window) against a share of BUDGET_CAP_PROVIDER_*, read off this environment's
# `.env` (main.tf), input and output apart. One alarm
# per enabled provider of the registry and per direction. A caller's own budget has no alarm — its
# dimension is unbounded — and is the spend-by-caller query below.
resource "aws_cloudwatch_metric_alarm" "provider_budget" {
  for_each = {
    for pair in setproduct(local.enabled_providers, ["input", "output"]) :
    "${pair[0]}-${pair[1]}" => { provider = pair[0], direction = pair[1] }
  }

  alarm_name          = "llm-client-${var.env}-budget-${each.key}"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = aws_cloudwatch_log_metric_filter.tokens[each.value.direction].metric_transformation[0].name
  namespace           = module.platform.metric_namespace
  dimensions          = { Provider = each.value.provider }
  period              = 86400
  statistic           = "Sum"
  threshold           = local.budget_caps[each.value.direction] * var.budget_alarm_percent / 100
  alarm_description   = "${each.value.provider}'s ${each.value.direction} tokens today reached ${var.budget_alarm_percent}% of its ceiling."
  alarm_actions       = [module.platform.alerts_topic_arn]
  treat_missing_data  = "notBreaching"
}

# ---- Refusals this service owns -------------------------------------------------------------------
# No alarm on any: each is ordinary at some rate, and what matters is a change in it.

resource "aws_cloudwatch_log_metric_filter" "refusals" {
  for_each = {
    budget         = "$.outcome = \"BudgetExhaustedError\""
    content        = "$.outcome = \"ContentRefusedError\""
    context-model  = "($.outcome = \"ContextOverflowError\" || $.outcome = \"UnknownModelError\")"
    preflight      = "$.preflight_rejected IS TRUE"
    missing-req-id = "$.outcome = \"MalformedRequestError\""
  }

  name           = "llm-client-${var.env}-refused-${each.key}"
  log_group_name = module.platform.log_group_name
  pattern        = "{ ${local.on_generate} && ${each.value} }"

  # No `default_value`: no ratio reads these, and each would publish a 0 for every other line.
  metric_transformation {
    name      = "Refused${replace(title(replace(each.key, "-", " ")), " ", "")}Count"
    namespace = module.platform.metric_namespace
    value     = "1"
  }
}

# ---- Process warm-up ----------------------------------------------------------------------------

resource "aws_cloudwatch_log_metric_filter" "startup_duration" {
  name           = "llm-client-${var.env}-startup-duration"
  log_group_name = module.platform.log_group_name
  pattern        = "{ $.event = \"startup_completed\" }"

  metric_transformation {
    name      = "StartupDurationMs"
    namespace = module.platform.metric_namespace
    value     = "$.duration_ms"
    unit      = "Milliseconds"
  }
}

# ---- Queries, not filters --------------------------------------------------------------------------
# A filter turns a line into a number; it can neither count unique values nor break spend down by
# an unbounded field. These are Logs Insights queries saved beside the log group, with no alarm.

resource "aws_cloudwatch_query_definition" "spend_by_caller" {
  name            = "llm-client-${var.env}/spend-by-caller"
  log_group_names = [module.platform.log_group_name]
  query_string    = <<-EOT
    filter event = "op_completed" and route = "${local.generate_route}" and ispresent(input_tokens)
    | stats sum(input_tokens) as input_tokens, sum(output_tokens) as output_tokens by client_id, provider, model
    | sort input_tokens desc
  EOT
}

resource "aws_cloudwatch_query_definition" "unique_callers" {
  name            = "llm-client-${var.env}/unique-callers"
  log_group_names = [module.platform.log_group_name]
  query_string    = <<-EOT
    filter event = "op_completed" and route = "${local.generate_route}"
    | stats count_distinct(client_id) as callers by bin(1d)
  EOT
}

resource "aws_cloudwatch_query_definition" "requested_vs_actual" {
  name            = "llm-client-${var.env}/requested-vs-actual-model"
  log_group_names = [module.platform.log_group_name]
  query_string    = <<-EOT
    filter event = "op_completed" and route = "${local.generate_route}" and outcome = "success"
    | stats count(*) as answers by requested_model, model, downgraded, failed_over
    | sort answers desc
  EOT
}
