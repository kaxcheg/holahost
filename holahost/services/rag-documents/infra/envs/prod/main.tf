# DB secrets (value-less, per frame spec) + log group (R-27). The app-role secret id matches
# scripts/bootstrap.py's f"holahost/{env}/rag-documents/db-password" exactly.

resource "aws_secretsmanager_secret" "db_password" {
  name                    = "holahost/${var.env}/rag-documents/db-password"
  recovery_window_in_days = 30
  # Value-less by design: no secret_string/secret_version here — filled manually via
  # `aws secretsmanager put-secret-value` per the runbook, so no secret material lands in state.
}

# The `postgres` container's own bootstrap superuser — a SEPARATE identity from the app role
# above, and it must stay separate. Owner isolation in this service is enforced only by Postgres
# RLS, which a superuser bypasses unconditionally (docker-compose.yml's `postgres` service spells
# out the full reasoning), so this password must never equal `db_password`: sharing one value
# would let anything holding the app's credentials log straight back into the bypass.
#
# Used by the deploy only (ssm-migrate-deploy: migrations, then scripts/provision_app_role.py) and
# by the `postgres` container's initdb — never by the running application, which authenticates as
# the unprivileged role instead.
resource "aws_secretsmanager_secret" "db_superuser_password" {
  name                    = "holahost/${var.env}/rag-documents/db-superuser-password"
  recovery_window_in_days = 30
  # Value-less, same as db_password — filled manually per the runbook.
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/holahost/${var.env}/rag-documents"
  retention_in_days = var.log_retention_days
}
