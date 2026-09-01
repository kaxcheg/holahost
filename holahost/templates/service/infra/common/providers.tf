provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project     = "holahost"
      Service     = "<svc>"
      ManagedBy   = "terraform"
      Environment = "common"
    }
  }
}
