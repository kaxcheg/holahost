# Default AWS provider (deploy region from config.yaml). The us_east_1 alias is required because
# CloudFront only accepts ACM certs issued in us-east-1 — the route53 module's cert uses it.
provider "aws" {
  region = local.cfg.aws_region

  default_tags {
    tags = {
      Project     = local.project
      Environment = local.env
      ManagedBy   = "terraform"
    }
  }
}

provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
}
