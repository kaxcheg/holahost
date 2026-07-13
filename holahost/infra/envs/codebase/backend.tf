# S3 backend with native state locking. Bucket created manually once — see holahost/infra/README.md.
terraform {
  backend "s3" {
    bucket       = "holahost-tfstate-codebase"
    key          = "codebase/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
