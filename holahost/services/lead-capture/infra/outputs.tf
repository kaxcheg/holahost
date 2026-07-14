# Outputs the hosting app's edge (gateway root) consumes via terraform_remote_state to mount the service.
output "function_url_domain" {
  value       = module.lambda.function_url_domain
  description = "Lambda Function URL host (no scheme/trailing slash) — the app gateway's /api/capture-lead/* origin."
}

output "api_function_name" {
  value       = module.lambda.api_function_name
  description = "Request Lambda name — the app gateway grants CloudFront lambda:InvokeFunctionUrl on it."
}
