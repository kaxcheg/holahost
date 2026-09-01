# This service's own metrics — everything that has to know a route or a domain field. The
# platform half (log group, alert topic, 5xx, auth failures, rate-limit refusals) comes from
# `module.platform`; these publish into its namespace and alarm through its topic.
#
# `route` has TWO FORMATS, and the filters below depend on the difference:
#   - success: a bare route TEMPLATE, no prefix — "POST /documents", "PUT /documents/{id}".
#   - failure: the RESOLVED path, with the /api/rag-documents prefix and a real id.
#   The prefix never appears on a success line, so its presence alone identifies a failure.
#
# `outcome` mixes error identities (an exception class's own name) with bare numeric
# statuses. Specific values match cleanly; "all 4xx" does not, since the identities share no
# prefix — so the failure-rate metrics are built from the route format instead.
#
# The literals are this service's contract, copied: an error class renamed in the code and
# not here stops matching silently, and `treat_missing_data = "notBreaching"` then reads the
# dead metric as health.
#
# p50/p90/p95/p99 are not separate metrics: IngestDurationMs and SearchDurationMs carry the
# raw data points, and a percentile is computed from them at alarm time.
#
# Percentile and ratio alarms use their own period (1h ingest / 15m search): a "p95" over one
# or two samples is noise, and ingest is structurally rarer than search.
# `datapoints_to_alarm` tolerates one sparse window rather than resetting on any gap.

# ---- Duration (§8.7 row 1) ------------------------------------------------------------------

resource "aws_cloudwatch_log_metric_filter" "ingest_duration" {
  name           = "rag-documents-${var.env}-ingest-duration"
  log_group_name = module.platform.log_group_name
  pattern        = "{ $.event = \"op_completed\" && $.outcome = \"success\" && ($.route = \"POST /documents\" || $.route = \"PUT /documents/{id}\") }"

  metric_transformation {
    name      = "IngestDurationMs"
    namespace = module.platform.metric_namespace
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
  alarm_actions       = [module.platform.alerts_topic_arn]
  treat_missing_data  = "notBreaching"
}

resource "aws_cloudwatch_log_metric_filter" "search_duration" {
  name           = "rag-documents-${var.env}-search-duration"
  log_group_name = module.platform.log_group_name
  pattern        = "{ $.event = \"op_completed\" && $.outcome = \"success\" && $.route = \"POST /documents/{id}/search\" }"

  metric_transformation {
    name      = "SearchDurationMs"
    namespace = module.platform.metric_namespace
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
  alarm_actions       = [module.platform.alerts_topic_arn]
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
  log_group_name = module.platform.log_group_name
  pattern        = "{ $.event = \"op_completed\" && $.outcome = \"success\" && ($.route = \"POST /documents\" || $.route = \"PUT /documents/{id}\") }"

  metric_transformation {
    name      = "IngestStageMs${title(each.key)}"
    namespace = module.platform.metric_namespace
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
  log_group_name = module.platform.log_group_name
  pattern        = "{ $.event = \"op_completed\" && $.outcome = \"success\" && $.route = \"POST /documents/{id}/search\" && $.hits > 0 }"

  metric_transformation {
    name      = "SearchTopScore"
    namespace = module.platform.metric_namespace
    value     = "$.top_score"
  }
}

# ---- Volume / adoption (business-facing, not in §8.7 — legible to a non-developer) -----------

resource "aws_cloudwatch_log_metric_filter" "document_created" {
  name           = "rag-documents-${var.env}-document-created"
  log_group_name = module.platform.log_group_name
  pattern        = "{ $.event = \"op_completed\" && $.outcome = \"success\" && $.route = \"POST /documents\" }"

  metric_transformation {
    name      = "DocumentCreatedCount"
    namespace = module.platform.metric_namespace
    value     = "1"
  }
}

resource "aws_cloudwatch_log_metric_filter" "search_count" {
  name           = "rag-documents-${var.env}-search-count"
  log_group_name = module.platform.log_group_name
  pattern        = "{ $.event = \"op_completed\" && $.outcome = \"success\" && $.route = \"POST /documents/{id}/search\" }"

  metric_transformation {
    name          = "SearchCount"
    namespace     = module.platform.metric_namespace
    value         = "1"
    default_value = 0
  }
}

# ---- §8.7 row 4: empty-search ratio (proxy for SIMILARITY_THRESHOLD miscalibration) -----------

resource "aws_cloudwatch_log_metric_filter" "empty_search" {
  name           = "rag-documents-${var.env}-empty-search"
  log_group_name = module.platform.log_group_name
  pattern        = "{ $.event = \"op_completed\" && $.outcome = \"success\" && $.route = \"POST /documents/{id}/search\" && $.hits = 0 }"

  metric_transformation {
    name      = "EmptySearchCount"
    namespace = module.platform.metric_namespace
    value     = "1"
  }
}

# ---- §8.7 row 6: chunk-count distribution ------------------------------------------------------

resource "aws_cloudwatch_log_metric_filter" "ingest_chunk_count" {
  name           = "rag-documents-${var.env}-ingest-chunk-count"
  log_group_name = module.platform.log_group_name
  pattern        = "{ $.event = \"op_completed\" && $.outcome = \"success\" && ($.route = \"POST /documents\" || $.route = \"PUT /documents/{id}\") }"

  metric_transformation {
    name      = "IngestChunkCount"
    namespace = module.platform.metric_namespace
    value     = "$.chunk_count"
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
  log_group_name = module.platform.log_group_name
  pattern        = "{ $.event = \"op_completed\" && $.outcome = \"success\" && ($.route = \"POST /documents\" || $.route = \"PUT /documents/{id}\") }"

  metric_transformation {
    name      = "IngestSuccessCount"
    namespace = module.platform.metric_namespace
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
  log_group_name = module.platform.log_group_name
  pattern        = "{ $.event = \"op_completed\" && ($.route = \"POST /api/rag-documents/documents\" || $.route = \"PUT /api/rag-documents/documents/*\") }"

  metric_transformation {
    name          = "IngestFailureCount"
    namespace     = module.platform.metric_namespace
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
  alarm_actions       = [module.platform.alerts_topic_arn]
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
  log_group_name = module.platform.log_group_name
  pattern        = "{ $.event = \"op_completed\" && $.route = %^POST /api/rag-documents/documents/[^/]+/search$% }"

  metric_transformation {
    name          = "SearchFailureCount"
    namespace     = module.platform.metric_namespace
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
  alarm_actions       = [module.platform.alerts_topic_arn]
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

# ---- Refusals this service owns --------------------------------------------------------------
# Identities from this service's own ERROR_CONTRACT (§7.6), plus the error its edge answers a
# missing X-Request-ID with. No alarm on any: each is ordinary at some rate, and what matters
# is a change in it. `UploadTooLargeError` and `PayloadTooLargeError` share one metric — both
# are the 413 of §7.6, and the question is how often a caller sends too much.

resource "aws_cloudwatch_log_metric_filter" "refused_too_large" {
  name           = "rag-documents-${var.env}-refused-too-large"
  log_group_name = module.platform.log_group_name
  pattern        = "{ $.event = \"op_completed\" && ($.outcome = \"UploadTooLargeError\" || $.outcome = \"PayloadTooLargeError\") }"

  metric_transformation {
    name          = "RefusedTooLargeCount"
    namespace     = module.platform.metric_namespace
    value         = "1"
    default_value = 0
  }
}

resource "aws_cloudwatch_log_metric_filter" "refused_media_type" {
  name           = "rag-documents-${var.env}-refused-media-type"
  log_group_name = module.platform.log_group_name
  pattern        = "{ $.event = \"op_completed\" && $.outcome = \"UnsupportedMediaTypeError\" }"

  metric_transformation {
    name          = "RefusedMediaTypeCount"
    namespace     = module.platform.metric_namespace
    value         = "1"
    default_value = 0
  }
}

resource "aws_cloudwatch_log_metric_filter" "refused_parse" {
  name           = "rag-documents-${var.env}-refused-parse"
  log_group_name = module.platform.log_group_name
  pattern        = "{ $.event = \"op_completed\" && $.outcome = \"DocumentParseError\" }"

  metric_transformation {
    name          = "RefusedParseCount"
    namespace     = module.platform.metric_namespace
    value         = "1"
    default_value = 0
  }
}

# Non-zero means a caller is reaching the service without passing through the gateway: every
# intended entry path attaches X-Request-ID unconditionally.
resource "aws_cloudwatch_log_metric_filter" "missing_request_id" {
  name           = "rag-documents-${var.env}-missing-request-id"
  log_group_name = module.platform.log_group_name
  pattern        = "{ $.event = \"op_completed\" && $.outcome = \"MalformedRequestError\" }"

  metric_transformation {
    name          = "MissingRequestIdCount"
    namespace     = module.platform.metric_namespace
    value         = "1"
    default_value = 0
  }
}

# ---- Process warm-up -------------------------------------------------------------------------
# `startup_completed`, not `op_completed`: the model load happens before the process serves
# anything, and it is what the deploy's smoke check waits out.

resource "aws_cloudwatch_log_metric_filter" "startup_duration" {
  name           = "rag-documents-${var.env}-startup-duration"
  log_group_name = module.platform.log_group_name
  pattern        = "{ $.event = \"startup_completed\" }"

  metric_transformation {
    name      = "StartupDurationMs"
    namespace = module.platform.metric_namespace
    value     = "$.duration_ms"
    unit      = "Milliseconds"
  }
}

# ---- Volume, the two writes the adoption view was missing -------------------------------------

resource "aws_cloudwatch_log_metric_filter" "document_replaced" {
  name           = "rag-documents-${var.env}-document-replaced"
  log_group_name = module.platform.log_group_name
  pattern        = "{ $.event = \"op_completed\" && $.outcome = \"success\" && $.route = \"PUT /documents/{id}\" }"

  metric_transformation {
    name          = "DocumentReplacedCount"
    namespace     = module.platform.metric_namespace
    value         = "1"
    default_value = 0
  }
}

resource "aws_cloudwatch_log_metric_filter" "document_deleted" {
  name           = "rag-documents-${var.env}-document-deleted"
  log_group_name = module.platform.log_group_name
  pattern        = "{ $.event = \"op_completed\" && $.outcome = \"success\" && $.route = \"DELETE /documents/{id}\" }"

  metric_transformation {
    name          = "DocumentDeletedCount"
    namespace     = module.platform.metric_namespace
    value         = "1"
    default_value = 0
  }
}
