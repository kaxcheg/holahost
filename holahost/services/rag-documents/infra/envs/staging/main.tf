# The platform half of this environment: log group, alert topic, and the alarms and filters
# that follow from `op_completed`'s core fields. Everything this service adds on top is in
# `observability.tf` and `dashboard.tf`; its secrets are below.

module "platform" {
  source = "../../../../../infra/modules/service-observability"

  service_name            = "rag-documents"
  env                     = var.env
  alert_email             = var.alert_email
  log_retention_days      = var.log_retention_days
  metric_namespace_prefix = "RagDocuments"
}

# ---- Secrets ---------------------------------------------------------------------------
# Here rather than in a platform module: the resource is five lines, so the `module` block
# that called it would cost what it saved, and the one thing a module would centralise — the
# `holahost/<env>/<svc>/<name>` convention — is spelled a second time regardless, in
# `scripts/bootstrap.py`, which builds the same id in Python to read the value back.
#
# Value-less by design: no `secret_string`, so no secret material lands in state. The values
# are filled in once by hand, per the runbook.
#
# The app role's own password, and the `postgres` container's bootstrap superuser — a
# SEPARATE identity, and it must stay separate. Owner isolation in this service is enforced
# only by Postgres RLS, which a superuser bypasses unconditionally, so these two values must
# never be equal: sharing one would let anything holding the app's credentials log straight
# back into the bypass. The superuser pair is used by the deploy only (migrations, then role
# provisioning) and by the container's own initdb — never by the running application.

resource "aws_secretsmanager_secret" "this" {
  for_each = toset(["db-password", "db-superuser-password"])

  name = "holahost/${var.env}/rag-documents/${each.key}"

  # 0 on staging: recreating the environment must not collide with the tombstone of the
  # last one. Prod keeps the default window, where an accidental delete has to be
  # recoverable — which is why this number is per-environment and not a module input.
  recovery_window_in_days = 0
}
