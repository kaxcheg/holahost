# CloudFront is global (default provider); the viewer cert is referenced by ARN (us-east-1, `common`).
provider "aws" {
  region = local.cfg.aws_region

  default_tags {
    tags = {
      Project     = local.project
      Environment = local.env
      Component   = "gateway"
      ManagedBy   = "terraform"
    }
  }
}
