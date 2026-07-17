# The service resources (Lambda, Secrets Manager, observability) live in the deploy region only.
provider "aws" {
  region = local.platform.aws_region

  default_tags {
    tags = {
      Project     = local.project
      Environment = local.env
      Service     = "lead-capture"
      ManagedBy   = "terraform"
    }
  }
}
