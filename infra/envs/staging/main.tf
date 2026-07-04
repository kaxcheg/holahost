# Module instances for this env. Static config from infra/config.yaml (single source); shared
# resources (frontend bucket, hosted zone, ACM cert) live in the `shared` root and are read here
# via data sources. ecr / lambda / observability land in I-08 … I-13.
locals {
  cfg     = yamldecode(file("${path.module}/../../config.yaml"))
  project = local.cfg.project
  env     = "staging"
  env_cfg = local.cfg.envs[local.env]
}

module "sm" {
  source = "../../modules/sm"

  env                     = local.env
  recovery_window_in_days = local.env_cfg.recovery_window_in_days
}

# Shared resources (frontend bucket, hosted zone, ACM cert) are owned by the `shared` root and
# read here via data sources — apply `shared` before this env.
data "aws_s3_bucket" "frontend" {
  bucket = local.cfg.frontend_bucket
}

data "aws_route53_zone" "primary" {
  name = local.cfg.domain
}

data "aws_acm_certificate" "frontend" {
  provider    = aws.us_east_1
  domain      = local.cfg.domain
  statuses    = ["ISSUED"]
  most_recent = true
}

module "cloudfront" {
  source = "../../modules/cloudfront"

  name_prefix                 = local.env_cfg.name_prefix
  aliases                     = [local.env_cfg.subdomain]
  price_class                 = local.env_cfg.price_class
  bucket_regional_domain_name = data.aws_s3_bucket.frontend.bucket_regional_domain_name
  acm_certificate_arn         = data.aws_acm_certificate.frontend.arn
  route53_zone_id             = data.aws_route53_zone.primary.zone_id
}
