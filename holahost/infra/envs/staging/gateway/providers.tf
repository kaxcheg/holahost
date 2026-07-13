# CloudFront is global (managed via the default provider); the viewer cert is referenced by ARN
# (issued in us-east-1 by the `common` root), so no us-east-1 provider is needed here.
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
