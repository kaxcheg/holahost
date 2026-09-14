# One root per environment (not workspace-selected) — each env's state is fully independent,
# never a shared key with implicit workspace namespacing.
terraform {
  backend "s3" {
    bucket       = "holahost-tfstate-common"
    key          = "llm-client/envs/prod/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
