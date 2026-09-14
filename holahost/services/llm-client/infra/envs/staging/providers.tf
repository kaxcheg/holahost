provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project     = "holahost"
      Service     = "llm-client"
      ManagedBy   = "terraform"
      Environment = var.env
    }
  }
}
