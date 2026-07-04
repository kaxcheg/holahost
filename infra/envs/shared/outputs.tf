output "frontend_bucket" {
  description = "Frontend bucket name."
  value       = module.s3_frontend.bucket_id
}

output "route53_name_servers" {
  description = "Delegate these NS at the domain registrar (one-time)."
  value       = module.route53.name_servers
}

output "acm_certificate_arn" {
  description = "Validated ACM cert ARN."
  value       = module.route53.acm_certificate_arn
}
