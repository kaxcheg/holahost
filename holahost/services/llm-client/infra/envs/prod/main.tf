# The platform half of this environment: log group, alert topic, and the alarms and filters
# that follow from `op_completed`'s core fields. Anything this service adds on top — a metric
# that has to know a route or a domain field — goes in an `observability.tf` beside this
# file, where the route names are visible. Its secrets are below.

module "platform" {
  source = "../../../../../infra/modules/service-observability"

  service_name            = "llm-client"
  env                     = var.env
  alert_email             = var.alert_email
  log_retention_days      = var.log_retention_days
  metric_namespace_prefix = "LlmClient"
}

# ---- Secrets ---------------------------------------------------------------------------
# Here rather than in a platform module: the resource is five lines, so the `module` block
# that called it would cost what it saved, and the one thing a module would centralise — the
# `holahost/<env>/llm-client/<name>` convention — is spelled a second time regardless, in
# `scripts/bootstrap.py`, which builds the same id in Python to read the value back.
#
# Value-less by design: no `secret_string`, so no secret material lands in state. The values
# are filled in once by hand, per the runbook. A service with external providers adds one
# name per key; one that stores nothing drops this resource and its outputs entirely.

resource "aws_secretsmanager_secret" "this" {
  for_each = toset(["db-password", "db-superuser-password"])

  name = "holahost/${var.env}/llm-client/${each.key}"

  # 30 days on prod: an accidental delete has to be recoverable. Staging sets 0 instead, so
  # recreating the environment does not collide with the tombstone of the last one — which
  # is why this number is per-environment and not a module input.
  recovery_window_in_days = 30
}
