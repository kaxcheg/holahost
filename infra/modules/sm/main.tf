resource "aws_secretsmanager_secret" "this" {
  for_each = toset(var.secret_keys)

  name                    = "holahost/${var.env}/${each.key}"
  recovery_window_in_days = var.recovery_window_in_days

  # Value-less by design (§10.3, ADR variant B): no secret_string and no
  # aws_secretsmanager_secret_version. Values are written out-of-IaC via
  # `aws secretsmanager put-secret-value` (see infra/README.md), so no secret
  # material ever lands in Terraform state. Tags come from the provider default_tags.
}
