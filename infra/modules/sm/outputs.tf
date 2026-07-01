output "secret_arns" {
  description = "Map of secret key => ARN. Consumed by the lambda module (I-12) to scope its GetSecretValue IAM policy to exactly these secrets (D-04)."
  value       = { for key, secret in aws_secretsmanager_secret.this : key => secret.arn }
}
