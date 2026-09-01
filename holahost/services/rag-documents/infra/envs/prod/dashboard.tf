# Every percentile and rate as its own always-visible line, nothing to configure per view: a
# percentile is a statistic CloudWatch applies to raw data points, so it cannot be a standalone
# metric, but a widget pre-configured with several stat lines is a standing artifact anyone can
# open. Body structure: a no-dimension metric entry is `[Namespace, MetricName]`, and a per-line
# override is a trailing object `{ "stat": "p95", "label": "p95" }`.
#
# Widget periods follow observability.tf's alarms (1h ingest / 15m search) rather than a flat
# 300s: a percentile over one or two samples is noise, and ingest is far rarer than search.

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
          title  = "Volume — writes and searches"
          region = var.aws_region
          view   = "timeSeries"
          stat   = "Sum"
          period = 300
          metrics = [
            # All three writes: created-alone reads as growth that is not happening once a
            # caller starts replacing documents in place.
            [local.ns, "DocumentCreatedCount", { label = "Documents created" }],
            [local.ns, "DocumentReplacedCount", { label = "Documents replaced" }],
            [local.ns, "DocumentDeletedCount", { label = "Documents deleted" }],
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
      # Every metric `observability.tf` publishes appears here, with or without an alarm: a
      # filter with neither is one nobody will find without knowing it exists.
      {
        type = "metric", x = 0, y = 18, width = 12, height = 6
        properties = {
          title  = "Ingest stage breakdown (p95) — where the budget goes"
          region = var.aws_region
          view   = "timeSeries"
          period = var.ingest_metric_period_seconds
          stat   = "p95"
          # Stacked: the four stages sum to the ingest duration, so the reading is which
          # band grew.
          stacked = true
          metrics = [
            [local.ns, "IngestStageMsParse", { label = "parse" }],
            [local.ns, "IngestStageMsChunk", { label = "chunk" }],
            [local.ns, "IngestStageMsEmbed", { label = "embed" }],
            [local.ns, "IngestStageMsPersist", { label = "persist" }],
          ]
          annotations = {
            horizontal = [{ value = var.ingestion_p95_budget_ms, label = "INGESTION_P95_BUDGET", color = "#d62728" }]
          }
        }
      },
      {
        type = "metric", x = 12, y = 18, width = 12, height = 6
        properties = {
          title  = "Search quality — top_score and result rate"
          region = var.aws_region
          view   = "timeSeries"
          period = var.search_metric_period_seconds
          # Two units in one widget: a score distribution drifting down together with the
          # result rate is the calibration signal, and split across two widgets it is missed.
          yAxis = { left = { min = 0, max = 1 }, right = { min = 0, max = 100 } }
          metrics = [
            [local.ns, "SearchTopScore", { stat = "p50", label = "top_score p50" }],
            [local.ns, "SearchTopScore", { stat = "p90", label = "top_score p90" }],
            [local.ns, "SearchTopScore", { stat = "p10", label = "top_score p10" }],
            [local.ns, "SearchCount", { id = "sc", visible = false, stat = "Sum" }],
            [local.ns, "EmptySearchCount", { id = "es", visible = false, stat = "Sum" }],
            # No standing metric: a filter turns a line into a number and cannot divide one
            # metric by another, so the ratio exists only as math.
            [{ expression = "((sc-es)/sc)*100", label = "Result rate %", id = "rr", yAxis = "right" }],
          ]
          # No `SIMILARITY_THRESHOLD` reference line: it is an application constant (§3.7),
          # and a Terraform copy would drift the first time the real one is calibrated. The
          # p95 budgets are mirrored only because an alarm needs its threshold here.
        }
      },
      {
        type = "metric", x = 0, y = 24, width = 12, height = 6
        properties = {
          title  = "Refusals this service owns"
          region = var.aws_region
          view   = "timeSeries"
          stat   = "Sum"
          period = 300
          metrics = [
            # Separate from the platform's 5xx/rate-limit/auth widget: these say something
            # about the caller's integration, not about the service's health.
            [local.ns, "RefusedTooLargeCount", { label = "413 — body/file too large" }],
            [local.ns, "RefusedMediaTypeCount", { label = "415 — MIME outside the whitelist" }],
            [local.ns, "RefusedParseCount", { label = "422 — could not parse the document" }],
            [local.ns, "MissingRequestIdCount", { label = "422 — no X-Request-ID (bypassing the gateway)" }],
          ]
        }
      },
      {
        type = "metric", x = 12, y = 24, width = 12, height = 6
        properties = {
          title  = "Process warm-up (startup_completed)"
          region = var.aws_region
          view   = "timeSeries"
          # Maximum, not an average: a process starts once, and what matters is the worst
          # start in the window — the wait the deploy's smoke check has to outlast.
          stat   = "Maximum"
          period = 300
          metrics = [
            [local.ns, "StartupDurationMs", { label = "Model load + guards" }],
          ]
        }
      },
    ]
  })
}
