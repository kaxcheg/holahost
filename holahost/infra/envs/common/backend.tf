# S3 backend with native state locking (Terraform >= 1.10 use_lockfile; no DynamoDB).
# The bucket is created manually once — see holahost/infra/README.md.
terraform {
  backend "s3" {
    bucket       = "holahost-tfstate-common"
    key          = "common/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
