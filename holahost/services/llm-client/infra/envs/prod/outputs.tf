output "db_password_secret_name" {
  value = aws_secretsmanager_secret.this["db-password"].name
}

output "db_superuser_password_secret_name" {
  value = aws_secretsmanager_secret.this["db-superuser-password"].name
}

output "provider_key_secret_names" {
  description = "Each provider key's secret, by its `api_key_ref` in the registry."
  value       = { for ref in local.provider_key_refs : ref => aws_secretsmanager_secret.this[ref].name }
}

output "log_group_name" {
  value = module.platform.log_group_name
}
