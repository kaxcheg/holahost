# Metrics sourced from the REAL op_completed structured-log event
# (backend/app/interface/http/router.py::_log_success, errors.py::_log_failure), not spec prose —
# covers every §8.7 metrics-table row that has actual supporting log data, plus adoption/business
# metrics not in §8.7 at all. `stage_ms` and `top_score` are now among them: an earlier revision
# of this file recorded that both were "never populated by any caller", which had stopped being
# true — `_log_success` passes `stage_ms=timer.as_dict()` on create/replace and
# `top_score=result.hits[0].score` on search, and `_StageTimer` exists for no other purpose. Both
# are read below, which is what §8.7's "разбивка ingest по стадиям" and "распределение top_score"
# rows asked for: without the first, the ingest p95 alarm fires with no way to tell a slow parse
# from a slow embed or a slow persist, and without the second, SIMILARITY_THRESHOLD (§3.7, "калибруется
# замером") has nothing to be calibrated against.
#
# `route` has TWO DIFFERENT FORMATS depending on outcome — found by reading the real code, not
# assumed:
#   - success (_log_success): a bare route TEMPLATE, no prefix, literal placeholder —
#     "POST /documents", "PUT /documents/{id}", "POST /documents/{id}/search",
#     "GET /documents/{id}", "DELETE /documents/{id}".
#   - failure (_log_failure): f"{method} {request.url.path}" — the RESOLVED path, WITH the
#     /api/rag-documents prefix and a real document_id.
#   The resolved-path prefix never appears in success-path logging, so its mere presence reliably
#   identifies "this was a failed request" without needing to also check `outcome`.
#
# outcome ∈ {"success", "InternalError", "RateLimitExceededError", "InvalidPayloadError", "401",
#            "503", str(status_code)} — a mix of error identities (each one an exception class's
# own name, §7.6) and bare numeric-status strings. Clean enough to match specific known values
# (RateLimitExceededError, 401/403, the 5xx set below) but NOT clean enough for a general "all 4xx"
# filter — the identities share no prefix — so §8.7's "доля неуспешных по классам" row is only
# half-covered here (5xx). A raw numeric status_code field logged unconditionally would close this
# cleanly — flagged, not fixed here (same scope boundary as stage_ms/top_score).
#
# These literals are the service's contract, copied: an error class renamed in the code and not
# here silently stops matching, and `treat_missing_data = "notBreaching"` then reads the dead
# metric as health. `tests/unit/interface/http/test_openapi.py` pins the vocabulary; keeping these
# in step with it is a manual step on any rename.
#
# p50/p90/p95/p99 etc. for duration are NOT separate metrics/filters — IngestDurationMs and
# SearchDurationMs already carry every raw data point; any percentile is computed from them at
# query/alarm time via `extended_statistic`, no per-percentile resource needed. The two *_p95
# alarms below are just one specific query against those two already-general metrics.
#
# Percentile/ratio alarms use var.ingest_metric_period_seconds/search_metric_period_seconds (1h/
# 15m defaults), not a flat 300s: a "p95" computed from 1-2 samples isn't a percentile, just noise
# — RATE_LIMIT_*_INGEST (60/hr) vs RATE_LIMIT_*_READ for search (600/hr) signals
# ingest is structurally ~10x rarer, and real volume at this early stage is likely well below even
# those ceilings. `datapoints_to_alarm` (M of N, not strictly consecutive) tolerates one sparse/
# missing window rather than resetting on any gap.

resource "aws_cloudwatch_log_metric_filter" "http_5xx" {
  name           = "rag-documents-${var.env}-5xx"
  log_group_name = aws_cloudwatch_log_group.app.name
  pattern        = "{ $.event = \"op_completed\" && ($.outcome = \"InternalError\" || $.outcome = \"5*\") }"

  metric_transformation {
    name      = "Http5xxCount"
    namespace = "RagDocuments/${var.env}"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "http_5xx" {
  alarm_name          = "rag-documents-${var.env}-5xx"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = aws_cloudwatch_log_metric_filter.http_5xx.metric_transformation[0].name
  namespace           = aws_cloudwatch_log_metric_filter.http_5xx.metric_transformation[0].namespace
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Any op_completed event with a 5xx outcome (§8.7)."
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"
}

# ---- Duration (§8.7 row 1) ------------------------------------------------------------------

resource "aws_cloudwatch_log_metric_filter" "ingest_duration" {
  name           = "rag-documents-${var.env}-ingest-duration"
  log_group_name = aws_cloudwatch_log_group.app.name
  pattern        = "{ $.event = \"op_completed\" && $.outcome = \"success\" && ($.route = \"POST /documents\" || $.route = \"PUT /documents/{id}\") }"

  metric_transformation {
    name      = "IngestDurationMs"
    namespace = "RagDocuments/${var.env}"
    value     = "$.duration_ms"
  }
}

resource "aws_cloudwatch_metric_alarm" "ingest_p95" {
  alarm_name          = "rag-documents-${var.env}-ingest-p95"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  datapoints_to_alarm = 2 # 2 of 3 windows, not strictly consecutive — tolerant of one sparse/gap window
  metric_name         = aws_cloudwatch_log_metric_filter.ingest_duration.metric_transformation[0].name
  namespace           = aws_cloudwatch_log_metric_filter.ingest_duration.metric_transformation[0].namespace
  period              = var.ingest_metric_period_seconds
  extended_statistic  = "p95"
  threshold           = var.ingestion_p95_budget_ms
  alarm_description   = "p95 create/replace duration exceeds INGESTION_P95_BUDGET (§3.7)."
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"
}

resource "aws_cloudwatch_log_metric_filter" "search_duration" {
  name           = "rag-documents-${var.env}-search-duration"
  log_group_name = aws_cloudwatch_log_group.app.name
  pattern        = "{ $.event = \"op_completed\" && $.outcome = \"success\" && $.route = \"POST /documents/{id}/search\" }"

  metric_transformation {
    name      = "SearchDurationMs"
    namespace = "RagDocuments/${var.env}"
    value     = "$.duration_ms"
  }
}

resource "aws_cloudwatch_metric_alarm" "search_p95" {
  alarm_name          = "rag-documents-${var.env}-search-p95"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 4
  datapoints_to_alarm = 3 # 3 of 4 windows, not strictly consecutive — tolerant of one sparse/gap window
  metric_name         = aws_cloudwatch_log_metric_filter.search_duration.metric_transformation[0].name
  namespace           = aws_cloudwatch_log_metric_filter.search_duration.metric_transformation[0].namespace
  period              = var.search_metric_period_seconds
  extended_statistic  = "p95"
  threshold           = var.search_p95_budget_ms
  alarm_description   = "p95 search duration exceeds SEARCH_P95_BUDGET (§3.7)."
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"
}

# ---- §8.7: ingest stage breakdown (stage_ms) ---------------------------------------------------
# One metric per stage rather than one filter with four transformations: a metric filter's value
# is a single JSON selector, so the stages are four series by construction. Nested selectors
# (`$.stage_ms.parse`) are what `_log_success` actually emits — `_StageTimer.as_dict()` writes the
# four keys as one object, and `record_remainder` guarantees they sum to `duration_ms`, so the four
# series can be read against IngestDurationMs directly.
#
# Same pattern as ingest_duration above, and for the same reason: `stage_ms` is populated on
# create/replace only (GET/DELETE pass None, search never has one), and only on success.

resource "aws_cloudwatch_log_metric_filter" "ingest_stage_ms" {
  for_each = toset(["parse", "chunk", "embed", "persist"])

  name           = "rag-documents-${var.env}-ingest-stage-${each.key}"
  log_group_name = aws_cloudwatch_log_group.app.name
  pattern        = "{ $.event = \"op_completed\" && $.outcome = \"success\" && ($.route = \"POST /documents\" || $.route = \"PUT /documents/{id}\") }"

  metric_transformation {
    name      = "IngestStageMs${title(each.key)}"
    namespace = "RagDocuments/${var.env}"
    value     = "$.stage_ms.${each.key}"
  }
}

# ---- §8.7: top_score distribution --------------------------------------------------------------
# Gated on `$.hits > 0`, not on the presence of `top_score`: `_log_success` sets
# `top_score=result.hits[0].score if result.hits else None`, so the two conditions are the same
# condition — and `hits` is an ordinary number the filter syntax handles without relying on how a
# JSON null interacts with an existence match.

resource "aws_cloudwatch_log_metric_filter" "search_top_score" {
  name           = "rag-documents-${var.env}-search-top-score"
  log_group_name = aws_cloudwatch_log_group.app.name
  pattern        = "{ $.event = \"op_completed\" && $.outcome = \"success\" && $.route = \"POST /documents/{id}/search\" && $.hits > 0 }"

  metric_transformation {
    name      = "SearchTopScore"
    namespace = "RagDocuments/${var.env}"
    value     = "$.top_score"
  }
}

# ---- Volume / adoption (business-facing, not in §8.7 — legible to a non-developer) -----------

resource "aws_cloudwatch_log_metric_filter" "document_created" {
  name           = "rag-documents-${var.env}-document-created"
  log_group_name = aws_cloudwatch_log_group.app.name
  pattern        = "{ $.event = \"op_completed\" && $.outcome = \"success\" && $.route = \"POST /documents\" }"

  metric_transformation {
    name      = "DocumentCreatedCount"
    namespace = "RagDocuments/${var.env}"
    value     = "1"
  }
}

resource "aws_cloudwatch_log_metric_filter" "search_count" {
  name           = "rag-documents-${var.env}-search-count"
  log_group_name = aws_cloudwatch_log_group.app.name
  pattern        = "{ $.event = \"op_completed\" && $.outcome = \"success\" && $.route = \"POST /documents/{id}/search\" }"

  metric_transformation {
    name          = "SearchCount"
    namespace     = "RagDocuments/${var.env}"
    value         = "1"
    default_value = 0
  }
}

# ---- §8.7 row 4: empty-search ratio (proxy for SIMILARITY_THRESHOLD miscalibration) -----------

resource "aws_cloudwatch_log_metric_filter" "empty_search" {
  name           = "rag-documents-${var.env}-empty-search"
  log_group_name = aws_cloudwatch_log_group.app.name
  pattern        = "{ $.event = \"op_completed\" && $.outcome = \"success\" && $.route = \"POST /documents/{id}/search\" && $.hits = 0 }"

  metric_transformation {
    name      = "EmptySearchCount"
    namespace = "RagDocuments/${var.env}"
    value     = "1"
  }
}

# ---- §8.7 row 6: chunk-count distribution ------------------------------------------------------

resource "aws_cloudwatch_log_metric_filter" "ingest_chunk_count" {
  name           = "rag-documents-${var.env}-ingest-chunk-count"
  log_group_name = aws_cloudwatch_log_group.app.name
  pattern        = "{ $.event = \"op_completed\" && $.outcome = \"success\" && ($.route = \"POST /documents\" || $.route = \"PUT /documents/{id}\") }"

  metric_transformation {
    name      = "IngestChunkCount"
    namespace = "RagDocuments/${var.env}"
    value     = "$.chunk_count"
  }
}

# ---- §8.7 row 7: rate-limit failure frequency --------------------------------------------------

resource "aws_cloudwatch_log_metric_filter" "rate_limit_failures" {
  name           = "rag-documents-${var.env}-rate-limit-failures"
  log_group_name = aws_cloudwatch_log_group.app.name
  pattern        = "{ $.event = \"op_completed\" && $.outcome = \"RateLimitExceededError\" }"

  metric_transformation {
    name      = "RateLimitFailureCount"
    namespace = "RagDocuments/${var.env}"
    value     = "1"
  }
}

# ---- §8.7 row 8: auth-failure frequency --------------------------------------------------------
# outcome="403" never actually fires in this service today (A-13: a foreign resource is 404, not
# 403 — owner-only means no "valid token, wrong permissions" path exists here), but matching it
# anyway keeps this consistent with the platform-wide 401/403 convention other services will hit.

resource "aws_cloudwatch_log_metric_filter" "auth_failures" {
  name           = "rag-documents-${var.env}-auth-failures"
  log_group_name = aws_cloudwatch_log_group.app.name
  pattern        = "{ $.event = \"op_completed\" && ($.outcome = \"401\" || $.outcome = \"403\") }"

  metric_transformation {
    name      = "AuthFailureCount"
    namespace = "RagDocuments/${var.env}"
    value     = "1"
  }
}

# ---- Success-rate alarms (metric math: success / (success + failure) * 100) -------------------
# "Failure" counts are identified by ROUTE FORMAT alone (the resolved-path /api/rag-documents/...
# shape), not by outcome — that shape only ever appears in _log_failure, so its presence alone
# reliably means "this request failed", regardless of which specific outcome code it was.
#
# search's failure route has the document_id embedded IN THE MIDDLE ("POST /api/rag-documents/
# documents/<uuid>/search") — CloudWatch's plain `*` wildcard is only documented with prefix/
# suffix examples (e.g. "123.123.*"), not confirmed for a middle-of-string position, so this uses
# regex (%...%, confirmed unambiguous for substring matching per AWS's own example
# `{ $.eventType = %Trail% }`) instead of risking an unverified `*` placement.

resource "aws_cloudwatch_log_metric_filter" "ingest_success_count" {
  name           = "rag-documents-${var.env}-ingest-success-count"
  log_group_name = aws_cloudwatch_log_group.app.name
  pattern        = "{ $.event = \"op_completed\" && $.outcome = \"success\" && ($.route = \"POST /documents\" || $.route = \"PUT /documents/{id}\") }"

  metric_transformation {
    name      = "IngestSuccessCount"
    namespace = "RagDocuments/${var.env}"
    value     = "1"
    # default_value, on all four filters feeding the two success-rate alarms: a metric filter
    # publishes a datapoint only when its pattern MATCHES, so without this a series with no
    # matches in a period is not "0", it is absent — and `(success/(success+failure))*100` over
    # an absent operand yields no value at all, leaving the alarm in INSUFFICIENT_DATA which
    # `treat_missing_data = "notBreaching"` then reads as healthy. That silences the alarm in
    # BOTH the states it exists to distinguish: a total outage (every request failing -> no
    # `success` datapoints) and, in reverse, ordinary healthy traffic (no `failure` datapoints).
    # `default_value = 0` emits an explicit 0 for every non-matching log event, so both operands
    # always have datapoints whenever the app logs anything at all, and the ratio evaluates.
    default_value = 0
  }
}

resource "aws_cloudwatch_log_metric_filter" "ingest_failure_count" {
  name           = "rag-documents-${var.env}-ingest-failure-count"
  log_group_name = aws_cloudwatch_log_group.app.name
  pattern        = "{ $.event = \"op_completed\" && ($.route = \"POST /api/rag-documents/documents\" || $.route = \"PUT /api/rag-documents/documents/*\") }"

  metric_transformation {
    name          = "IngestFailureCount"
    namespace     = "RagDocuments/${var.env}"
    value         = "1"
    default_value = 0
  }
}

resource "aws_cloudwatch_metric_alarm" "success_ingest_rate" {
  alarm_name          = "rag-documents-${var.env}-success-ingest-rate"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 3
  datapoints_to_alarm = 2 # same sparse-data tolerance as ingest_p95 — same period, same reasoning
  threshold           = var.success_rate_threshold_percent
  alarm_description   = "Ingest (create+replace) success rate dropped below the threshold."
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"

  metric_query {
    id          = "rate"
    expression  = "(success/(success+failure))*100"
    label       = "SuccessIngestRate"
    return_data = "true"
  }
  metric_query {
    id = "success"
    metric {
      metric_name = aws_cloudwatch_log_metric_filter.ingest_success_count.metric_transformation[0].name
      namespace   = aws_cloudwatch_log_metric_filter.ingest_success_count.metric_transformation[0].namespace
      period      = var.ingest_metric_period_seconds
      stat        = "Sum"
    }
  }
  metric_query {
    id = "failure"
    metric {
      metric_name = aws_cloudwatch_log_metric_filter.ingest_failure_count.metric_transformation[0].name
      namespace   = aws_cloudwatch_log_metric_filter.ingest_failure_count.metric_transformation[0].namespace
      period      = var.ingest_metric_period_seconds
      stat        = "Sum"
    }
  }
}

resource "aws_cloudwatch_log_metric_filter" "search_failure_count" {
  name           = "rag-documents-${var.env}-search-failure-count"
  log_group_name = aws_cloudwatch_log_group.app.name
  pattern        = "{ $.event = \"op_completed\" && $.route = %^POST /api/rag-documents/documents/[^/]+/search$% }"

  metric_transformation {
    name          = "SearchFailureCount"
    namespace     = "RagDocuments/${var.env}"
    value         = "1"
    default_value = 0
  }
}

resource "aws_cloudwatch_metric_alarm" "success_search_rate" {
  alarm_name          = "rag-documents-${var.env}-success-search-rate"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 4
  datapoints_to_alarm = 3 # same sparse-data tolerance as search_p95 — same period, same reasoning
  threshold           = var.success_rate_threshold_percent
  alarm_description   = "Search success rate dropped below the threshold."
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"

  metric_query {
    id          = "rate"
    expression  = "(success/(success+failure))*100"
    label       = "SuccessSearchRate"
    return_data = "true"
  }
  metric_query {
    id = "success"
    metric {
      metric_name = aws_cloudwatch_log_metric_filter.search_count.metric_transformation[0].name
      namespace   = aws_cloudwatch_log_metric_filter.search_count.metric_transformation[0].namespace
      period      = var.search_metric_period_seconds
      stat        = "Sum"
    }
  }
  metric_query {
    id = "failure"
    metric {
      metric_name = aws_cloudwatch_log_metric_filter.search_failure_count.metric_transformation[0].name
      namespace   = aws_cloudwatch_log_metric_filter.search_failure_count.metric_transformation[0].namespace
      period      = var.search_metric_period_seconds
      stat        = "Sum"
    }
  }
}

resource "aws_sns_topic" "alerts" {
  name = "rag-documents-${var.env}-alerts"
}

resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}
