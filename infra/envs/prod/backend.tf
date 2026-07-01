# S3 backend with native state locking (Terraform >= 1.10 `use_lockfile`; no DynamoDB).
# The bucket is created manually once — see infra/README.md (I-04).
terraform {
  backend "s3" {
    bucket       = "holahost-tfstate-prod"
    key          = "prod/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
