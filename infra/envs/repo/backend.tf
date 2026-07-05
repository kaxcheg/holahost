terraform {
  backend "s3" {
    bucket       = "holahost-tfstate-repo"
    key          = "repo/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
