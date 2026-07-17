# Consumed by the staging `gateway` root via terraform_remote_state to mount /api/lead-capture/*.
output "function_url_domain" {
  value       = module.lead_capture.function_url_domain
  description = "Lambda Function URL host — the gateway CloudFront origin for /api/lead-capture/*."
}

output "api_function_name" {
  value       = module.lead_capture.api_function_name
  description = "Request Lambda name — the gateway grants CloudFront lambda:InvokeFunctionUrl on it."
}

output "api_base_url" {
  value       = local.beenv["API_BASE_URL"]
  description = "Service mount path (from <env>.env API_BASE_URL) — single source: the gateway CloudFront behavior + the backend router both use it."
}
