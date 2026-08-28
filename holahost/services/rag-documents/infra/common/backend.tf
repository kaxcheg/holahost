# Native S3 locking (Terraform >= 1.10, no DynamoDB — matches the .tool-versions pin). The state
# bucket itself is a manual one-time platform bootstrap (frame spec: "bucket и таблица блокировок
# создаются однократно вне TF") — not created by this root, and doesn't exist yet in this repo.
terraform {
  backend "s3" {
    bucket       = "holahost-tfstate-common"
    key          = "rag-documents/common/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
