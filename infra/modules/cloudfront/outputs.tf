output "distribution_id" {
  description = "CloudFront distribution id (CI uses it for origin-path switch + invalidation)."
  value       = aws_cloudfront_distribution.frontend.id
}

output "distribution_arn" {
  description = "CloudFront distribution ARN."
  value       = aws_cloudfront_distribution.frontend.arn
}

output "distribution_domain_name" {
  description = "Distribution domain name (dxxxx.cloudfront.net)."
  value       = aws_cloudfront_distribution.frontend.domain_name
}
