output "db_password_secret_name" {
  value = aws_secretsmanager_secret.db_password.name
}

output "db_superuser_password_secret_name" {
  value = aws_secretsmanager_secret.db_superuser_password.name
}

output "log_group_name" {
  value = aws_cloudwatch_log_group.app.name
}
