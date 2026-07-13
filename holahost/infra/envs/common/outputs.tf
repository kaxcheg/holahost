# Consumed by the per-env `capture-lead` (bucket + ecr) and `gateway` (bucket + cert + zone) roots via
# terraform_remote_state, and by the runbook (name servers).
output "frontend_bucket_id" {
  value       = module.s3_frontend.bucket_id
  description = "Frontend bucket name."
}

output "frontend_bucket_arn" {
  value       = module.s3_frontend.bucket_arn
  description = "Frontend bucket ARN — the service exec role reads sample guidebook + system-prompt/* from it."
}

output "frontend_bucket_regional_domain_name" {
  value       = module.s3_frontend.bucket_regional_domain_name
  description = "Frontend bucket regional domain — the gateway CloudFront S3 origin."
}

output "route53_zone_id" {
  value       = module.route53.zone_id
  description = "Hosted zone id — the gateway alias A/AAAA records."
}

output "route53_name_servers" {
  value       = module.route53.name_servers
  description = "Zone name servers — delegate these at the registrar (one-time)."
}

output "acm_certificate_arn" {
  value       = module.route53.acm_certificate_arn
  description = "Validated ACM cert ARN (us-east-1) — the gateway viewer cert."
}

output "ecr_repository_urls" {
  value       = { for k, m in module.ecr : k => m.repository_url }
  description = "Map service => ECR repo URL. CI pushes images; the service root reads its repo for image_uri."
}
