# The AWS provider resolves its region, when not set here, from the AWS_REGION (then AWS_DEFAULT_REGION) env
# var at plan/apply time — set by CI (GitHub Actions workflow env) or locally (`export AWS_REGION`). This is
# the DEPLOY-time region; it is distinct from the app's runtime AWS_REGION (the Lambda runtime sets that for
# the app's boto3 / Secrets Manager) — same name, different source. Not committed to tfvars; route53 /
# cloudfront / ACM stay region-independent (the us-east-1 alias below).
provider "aws" {
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
# reference (I-11) use `provider = aws.us_east_1`. When var.region is already us-east-1 this aliases the
# same region as the default provider; it only diverges once the primary region is moved off us-east-1.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
}

# Module instances (secrets, ecr, s3_frontend, route53, cloudfront, lambda, observability, github_repo)
# are added to main.tf per env in I-06 … I-14.
