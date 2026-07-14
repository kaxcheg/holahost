output "function_url_domain" {
  description = "Function URL host (no scheme/trailing slash) — the /api/* CloudFront origin domain."
  value       = trimsuffix(trimprefix(aws_lambda_function_url.api.function_url, "https://"), "/")
}

output "api_function_name" {
  description = "Request Lambda name — the env root grants CloudFront lambda:InvokeFunctionUrl on it."
  value       = aws_lambda_function.api.function_name
}

output "api_log_group_name" {
  description = "API Lambda log group name — read by the observability module's metric filters."
  value       = aws_cloudwatch_log_group.api.name
}

output "cleanup_log_group_name" {
  description = "Cleanup Lambda log group name — read by the observability module's metric filters."
  value       = aws_cloudwatch_log_group.cleanup.name
}
