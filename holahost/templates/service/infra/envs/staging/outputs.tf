output "db_password_secret_name" {
  value = aws_secretsmanager_secret.this["db-password"].name
}

output "db_superuser_password_secret_name" {
  value = aws_secretsmanager_secret.this["db-superuser-password"].name
}

output "log_group_name" {
  value = module.platform.log_group_name
}
