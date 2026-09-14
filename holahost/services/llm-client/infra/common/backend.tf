# Native S3 locking (Terraform >= 1.10, no DynamoDB — matches the .tool-versions pin). The state
# bucket is a one-time platform bootstrap created outside Terraform, not by this root.
terraform {
  backend "s3" {
    bucket       = "holahost-tfstate-common"
    key          = "llm-client/common/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
