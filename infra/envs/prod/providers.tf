# The default AWS provider's region is set explicitly from var.aws_region (this env's terraform.tfvars) —
# the DEPLOY-time region, pinned in version control per env. It is distinct from the app's runtime
# AWS_REGION (a reserved var the Lambda runtime sets to the function's region for the app's boto3 /
# Secrets Manager); the lambda module (I-12) injects AWS_RESOURCES_REGION = var.aws_region so the app reads
# secrets from its own deploy region (§12.3).
provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "holahost"
      Environment = var.env
      ManagedBy   = "terraform"
    }
  }
}

# Secondary provider pinned to us-east-1. CloudFront only accepts ACM certificates issued in us-east-1,
# regardless of where the rest of the stack lives — so the ACM cert (I-10) and the CloudFront cert
# reference (I-11) use `provider = aws.us_east_1`. When var.aws_region is already us-east-1 this aliases
# the same region as the default provider; it only diverges once the primary region moves off us-east-1.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
}

# Module instances (sm, ecr, s3_frontend, route53, cloudfront, lambda, observability, github_repo)
# are added to main.tf per env in I-06 … I-14.
