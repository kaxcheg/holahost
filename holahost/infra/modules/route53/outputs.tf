output "zone_id" {
  description = "Route53 hosted zone id."
  value       = aws_route53_zone.primary.zone_id
}

output "zone_name" {
  description = "Hosted zone name."
  value       = aws_route53_zone.primary.name
}

output "name_servers" {
  description = "Zone name servers — delegate these at the domain registrar (runbook one-time step)."
  value       = aws_route53_zone.primary.name_servers
}

output "acm_certificate_arn" {
  description = "Validated ACM cert ARN (us-east-1). Referenced by per-env cloudfront via data.aws_acm_certificate."
  value       = aws_acm_certificate_validation.cert.certificate_arn
}
