terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
      # CloudFront ACM certs must live in us-east-1; caller passes the aliased provider.
      configuration_aliases = [aws.us_east_1]
    }
  }
}
