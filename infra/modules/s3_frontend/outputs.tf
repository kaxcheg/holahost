output "bucket_id" {
  description = "Frontend bucket name."
  value       = aws_s3_bucket.frontend.id
}

output "bucket_arn" {
  description = "Frontend bucket ARN."
  value       = aws_s3_bucket.frontend.arn
}

output "bucket_regional_domain_name" {
  description = "Regional domain name — CloudFront S3 origin domain (consumed by per-env cloudfront modules via data.aws_s3_bucket)."
  value       = aws_s3_bucket.frontend.bucket_regional_domain_name
}

output "sample_guidebook_key" {
  description = "S3 key of the sample-guidebook object — injected by lambda as SAMPLE_GUIDEBOOK_S3_KEY (I-12)."
  value       = aws_s3_object.sample_guidebook.key
}
