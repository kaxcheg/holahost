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
# are filled in once by hand, per the runbook.
#
# The provider keys are read off the registry the service validates at startup, one secret per
# `api_key_ref`: a name in this root and a reference in that file cannot drift apart, so no CI step
# has to compare them. Selected by having a reference rather than by `enabled`, so disabling a
# provider does not delete its secret — removing its block from the registry does, at the next
# apply, and with no recovery window here.
#
# The runtime settings come from this environment's `.env` the same way: the budget alarms compare
# against the provider ceilings the service itself enforces, not a copy of them.

locals {
  registry          = yamldecode(file("${path.module}/../../../backend/app/config/registry.yaml"))
  provider_key_refs = [for name, provider in local.registry.providers : provider.api_key_ref if try(provider.api_key_ref, null) != null]
  enabled_providers = [for name, provider in local.registry.providers : name if provider.enabled]
  settings          = { for pair in regexall("(?m)^([A-Z0-9_]+)=(.*)$", file("${path.module}/.env")) : pair[0] => pair[1] }
}

resource "aws_secretsmanager_secret" "this" {
  for_each = toset(concat(["db-password", "db-superuser-password"], local.provider_key_refs))

  name = "holahost/${var.env}/llm-client/${each.key}"

  # 0 on staging: recreating the environment must not collide with the tombstone of the
  # last one. Prod keeps a real window, where an accidental delete has to be recoverable —
  # which is why this number is per-environment and not a module input.
  recovery_window_in_days = 0
}
