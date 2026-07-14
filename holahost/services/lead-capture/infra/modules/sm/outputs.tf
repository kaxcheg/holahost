output "secret_arns" {
  description = "Map of secret key => ARN. Consumed by the lambda module (I-12) to scope its GetSecretValue IAM policy to exactly these secrets (D-04)."
  value       = { for key, secret in aws_secretsmanager_secret.this : key => secret.arn }
}

output "secret_keys" {
  description = "The secret key names (SM contract, default = mirror of sm_loader.SERVER_SIDE_SECRET_KEYS). The lambda_env parse uppercases these to drop them from be-env — one source, no third hardcoded list (D-04)."
  value       = var.secret_keys
}
