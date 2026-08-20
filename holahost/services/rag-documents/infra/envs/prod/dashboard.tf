# CloudWatch dashboard: every percentile/rate as its own always-visible line, zero per-view
# configuration — the concrete answer to "no manual counting" (percentile is a *statistic* CloudWatch
# applies to a metric's raw data points; there's no way to make a percentile its own standalone
# metric, but a dashboard widget pre-configured with multiple stat lines is a standing artifact
# anyone can open with nothing to set up). Syntax verified against AWS's own docs
# (AmazonCloudWatch-Dashboard-Body-Structure), not assumed: a no-dimension metric entry is
# `[Namespace, MetricName]`; a per-line statistic/label override is a trailing object
# `{ "stat": "p95", "label": "p95" }`; "stat" explicitly allows `p{{??}}` values.
#
# Widget periods use var.ingest_metric_period_seconds/search_metric_period_seconds (1h/15m
# defaults), not a flat 300s — same reasoning as observability.tf's alarms: a percentile computed
# from 1-2 samples in a 5-minute window isn't a percentile, just noise, and ingest is structurally
# far rarer than search (RATE_LIMIT_INGEST 60/hr/client vs RATE_LIMIT_DEFAULT 600/hr/client).

locals {
  ns = "RagDocuments/${var.env}"
}

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "rag-documents-${var.env}"

  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 12, height = 6
        properties = {
          title  = "Ingest duration (create+replace), by percentile"
          region = var.aws_region
          view   = "timeSeries"
          period = var.ingest_metric_period_seconds # rare event — needs a wide window per percentile point
          metrics = [
            [local.ns, "IngestDurationMs", { stat = "p50", label = "p50" }],
            [local.ns, "IngestDurationMs", { stat = "p90", label = "p90" }],
            [local.ns, "IngestDurationMs", { stat = "p95", label = "p95 (INGESTION_P95_BUDGET alarm)" }],
            [local.ns, "IngestDurationMs", { stat = "p99", label = "p99" }],
          ]
          annotations = {
            horizontal = [{ value = var.ingestion_p95_budget_ms, label = "INGESTION_P95_BUDGET", color = "#d62728" }]
          }
        }
      },
      {
        type = "metric", x = 12, y = 0, width = 12, height = 6
        properties = {
          title  = "Search duration, by percentile"
          region = var.aws_region
          view   = "timeSeries"
          period = var.search_metric_period_seconds
          metrics = [
            [local.ns, "SearchDurationMs", { stat = "p50", label = "p50" }],
            [local.ns, "SearchDurationMs", { stat = "p90", label = "p90" }],
            [local.ns, "SearchDurationMs", { stat = "p95", label = "p95 (SEARCH_P95_BUDGET alarm)" }],
            [local.ns, "SearchDurationMs", { stat = "p99", label = "p99" }],
          ]
          annotations = {
            horizontal = [{ value = var.search_p95_budget_ms, label = "SEARCH_P95_BUDGET", color = "#d62728" }]
          }
        }
      },
      {
        type = "metric", x = 0, y = 6, width = 12, height = 6
        properties = {
          title  = "Success rate (%) — ingest and search"
          region = var.aws_region
          view   = "timeSeries"
          # No single widget-level period: ingest and search need different windows (mixed in one
          # widget), so each metric below sets its own period explicitly instead of inheriting a
          # default here.
          yAxis = { left = { min = 0, max = 100 } }
          metrics = [
            [local.ns, "IngestSuccessCount", { id = "is1", visible = false, stat = "Sum", period = var.ingest_metric_period_seconds }],
            [local.ns, "IngestFailureCount", { id = "if1", visible = false, stat = "Sum", period = var.ingest_metric_period_seconds }],
            [{ expression = "(is1/(is1+if1))*100", label = "SuccessIngestRate", id = "ir" }], # no period here — inherits from is1/if1's own periods, which is all "expression" entries document supporting
            [local.ns, "SearchCount", { id = "ss1", visible = false, stat = "Sum", period = var.search_metric_period_seconds }],
            [local.ns, "SearchFailureCount", { id = "sf1", visible = false, stat = "Sum", period = var.search_metric_period_seconds }],
            [{ expression = "(ss1/(ss1+sf1))*100", label = "SuccessSearchRate", id = "sr" }], # no period — same reasoning as "ir" above
          ]
          annotations = {
            horizontal = [{ value = var.success_rate_threshold_percent, label = "alarm threshold", color = "#d62728" }]
          }
        }
      },
      {
        type = "metric", x = 12, y = 6, width = 12, height = 6
        properties = {
          title  = "Volume — documents created, searches run"
          region = var.aws_region
          view   = "timeSeries"
          stat   = "Sum"
          period = 300
          metrics = [
            [local.ns, "DocumentCreatedCount", { label = "Documents created" }],
            [local.ns, "SearchCount", { label = "Searches run" }],
          ]
        }
      },
      {
        type = "metric", x = 0, y = 12, width = 12, height = 6
        properties = {
          title  = "Failures — 5xx, rate limit, auth"
          region = var.aws_region
          view   = "timeSeries"
          stat   = "Sum"
          period = 300
          metrics = [
            [local.ns, "Http5xxCount", { label = "5xx" }],
            [local.ns, "RateLimitFailureCount", { label = "Rate-limited" }],
            [local.ns, "AuthFailureCount", { label = "Auth failures" }],
          ]
        }
      },
      {
        type = "metric", x = 12, y = 12, width = 12, height = 6
        properties = {
          title  = "Ingest chunk count (p95) / empty-search count"
          region = var.aws_region
          view   = "timeSeries"
          metrics = [
            [local.ns, "IngestChunkCount", { stat = "p95", label = "Chunk count p95 (MAX_CHUNKS_PER_DOCUMENT proxy)", period = var.ingest_metric_period_seconds }],
            [local.ns, "EmptySearchCount", { stat = "Sum", label = "Empty searches (SIMILARITY_THRESHOLD proxy)", period = var.search_metric_period_seconds }],
          ]
        }
      },
    ]
  })
}
