provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project     = "holahost"
      Service     = "rag-documents"
      ManagedBy   = "terraform"
      Environment = var.env
    }
  }
}
