# DB password secret (value-less, per frame spec) + log group (R-27). Secret id matches
# scripts/bootstrap.py's f"holahost/{env}/rag-documents/db-password" exactly.

resource "aws_secretsmanager_secret" "db_password" {
  name                    = "holahost/${var.env}/rag-documents/db-password"
  recovery_window_in_days = 0
  # Value-less by design: no secret_string/secret_version here — filled manually via
  # `aws secretsmanager put-secret-value` per the runbook, so no secret material lands in state.
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/holahost/${var.env}/rag-documents"
  retention_in_days = var.log_retention_days
}
