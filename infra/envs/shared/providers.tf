# Shared, single-instance resources owned by this root (frontend bucket + hosted zone + ACM cert),
# consumed by both staging and prod via data sources. Apply this root once, before staging/prod.
provider "aws" {
  region = local.cfg.aws_region

  default_tags {
    tags = {
      Project     = local.project
      Environment = "shared"
      ManagedBy   = "terraform"
    }
  }
}

# CloudFront ACM certs must be issued in us-east-1 (route53 module uses this alias).
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
}
