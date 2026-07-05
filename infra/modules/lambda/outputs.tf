output "function_url_domain" {
  description = "Function URL host (no scheme/trailing slash) — the /api/* CloudFront origin domain."
  value       = trimsuffix(trimprefix(aws_lambda_function_url.api.function_url, "https://"), "/")
}

output "api_function_name" {
  description = "Request Lambda name — the env root grants CloudFront lambda:InvokeFunctionUrl on it."
  value       = aws_lambda_function.api.function_name
}
