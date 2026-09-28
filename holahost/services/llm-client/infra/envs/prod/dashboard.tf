# One widget per concern, every metric observability.tf publishes on some widget: a metric neither
# alarmed nor shown is spend on a series nobody opens. Percentiles are stat lines of one raw
# series; shares are metric math over the same counters the alarms divide. A no-dimension metric
# entry is `[namespace, name]`, a per-line override a trailing object; a hidden operand carries
# `visible = false` and an `id` the expression names.

locals {
  ns = module.platform.metric_namespace
}

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "llm-client-${var.env}"

  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 12, height = 6
        properties = {
          title  = "Generations and success rate (%)"
          region = var.aws_region
          view   = "timeSeries"
          period = var.metric_period_seconds
          metrics = [
            [local.ns, "GenerateRequestCount", { stat = "Sum", id = "requests", label = "requests (every outcome)" }],
            [local.ns, "GenerateSuccessCount", { stat = "Sum", id = "success", label = "successes" }],
            [local.ns, "UpstreamFailureCount", { stat = "Sum", id = "upstream", visible = false }],
            [local.ns, "InternalErrorCount", { stat = "Sum", id = "internal", label = "InternalError" }],
            [{ expression = "(success/(success+upstream+internal))*100", label = "success rate % (service's fault only)", id = "rate", yAxis = "right" }],
          ]
          annotations = {
            horizontal = [{ value = var.success_rate_threshold_percent, label = "alarm", color = "#d62728", yAxis = "right" }]
          }
        }
      },
      {
        type = "metric", x = 12, y = 0, width = 12, height = 6
        properties = {
          title  = "Generation duration vs time inside the provider"
          region = var.aws_region
          view   = "timeSeries"
          period = var.metric_period_seconds
          metrics = [
            [local.ns, "GenerateDurationMs", { stat = "p50", label = "duration p50" }],
            [local.ns, "GenerateDurationMs", { stat = "p95", label = "duration p95 (alarm)" }],
            [local.ns, "ProviderMs", { stat = "p50", label = "provider p50" }],
            [local.ns, "ProviderMs", { stat = "p95", label = "provider p95" }],
          ]
          annotations = {
            horizontal = [{ value = var.generation_p95_budget_ms, label = "GENERATION_P95_BUDGET", color = "#d62728" }]
          }
        }
      },
      {
        type = "metric", x = 0, y = 6, width = 12, height = 6
        properties = {
          title  = "Upstream: failures (%), attempts, own timeouts"
          region = var.aws_region
          view   = "timeSeries"
          period = var.metric_period_seconds
          metrics = [
            [local.ns, "UpstreamFailureCount", { stat = "Sum", id = "upstream", visible = false }],
            [local.ns, "GenerateRequestCount", { stat = "Sum", id = "requests", visible = false }],
            [{ expression = "(upstream/requests)*100", label = "UpstreamLlmError %", id = "share" }],
            [local.ns, "Attempts", { stat = "Average", label = "attempts per success", yAxis = "right" }],
            [local.ns, "ProviderTimeouts", { stat = "Sum", label = "own timeouts (spend outside the log)", yAxis = "right" }],
          ]
          annotations = {
            horizontal = [{ value = var.upstream_share_threshold_percent, label = "alarm", color = "#d62728" }]
          }
        }
      },
      {
        type = "metric", x = 12, y = 6, width = 12, height = 6
        properties = {
          title  = "Answered by something other than asked (%)"
          region = var.aws_region
          view   = "timeSeries"
          period = var.downgraded_period_seconds
          metrics = [
            [local.ns, "DowngradedCount", { stat = "Sum", id = "downgraded", visible = false }],
            [local.ns, "FailedOverCount", { stat = "Sum", id = "failedover", visible = false }],
            [local.ns, "GenerateSuccessCount", { stat = "Sum", id = "success", visible = false }],
            [{ expression = "(downgraded/success)*100", label = "downgraded % (alarm)", id = "dshare" }],
            [{ expression = "(failedover/success)*100", label = "failed over %", id = "fshare" }],
          ]
          annotations = {
            horizontal = [{ value = var.downgraded_share_threshold_percent, label = "downgrade alarm", color = "#d62728" }]
          }
        }
      },
      {
        type = "metric", x = 0, y = 12, width = 12, height = 6
        properties = {
          title  = "Tokens per day, by provider (budget ceilings as lines)"
          region = var.aws_region
          view   = "timeSeries"
          period = 86400
          stat   = "Sum"
          metrics = concat(
            [for provider in local.enabled_providers : [local.ns, "InputTokens", "Provider", provider, { label = "${provider} input" }]],
            [for provider in local.enabled_providers : [local.ns, "OutputTokens", "Provider", provider, { label = "${provider} output", yAxis = "right" }]],
          )
          annotations = {
            horizontal = [
              { value = local.budget_caps.input, label = "input ceiling", color = "#d62728" },
              { value = local.budget_caps.output, label = "output ceiling", color = "#ff7f0e", yAxis = "right" },
            ]
          }
        }
      },
      {
        type = "metric", x = 12, y = 12, width = 12, height = 6
        properties = {
          title  = "Refusals this service owns"
          region = var.aws_region
          view   = "timeSeries"
          period = var.metric_period_seconds
          stat   = "Sum"
          metrics = [
            [local.ns, "RefusedBudgetCount", { label = "BudgetExhaustedError" }],
            [local.ns, "RefusedContentCount", { label = "ContentRefusedError" }],
            [local.ns, "RefusedContextModelCount", { label = "ContextOverflowError / UnknownModelError" }],
            [local.ns, "RefusedPreflightCount", { label = "pre-flight (RequestTooSlowForSyncError)" }],
            [local.ns, "RefusedMissingReqIdCount", { label = "MalformedRequestError (bypassed the gateway)" }],
          ]
        }
      },
      {
        type = "metric", x = 0, y = 18, width = 12, height = 6
        properties = {
          title  = "Answer length (output tokens per generation)"
          region = var.aws_region
          view   = "timeSeries"
          period = var.metric_period_seconds
          metrics = [
            for provider in local.enabled_providers :
            [local.ns, "OutputTokens", "Provider", provider, { stat = "Average", label = "${provider} average" }]
          ]
        }
      },
      {
        type = "metric", x = 12, y = 18, width = 12, height = 6
        properties = {
          title  = "Process warm-up (startup_completed)"
          region = var.aws_region
          view   = "timeSeries"
          period = 300
          metrics = [
            [local.ns, "StartupDurationMs", { stat = "Maximum", label = "startup ms" }],
          ]
        }
      },
    ]
  })
}
