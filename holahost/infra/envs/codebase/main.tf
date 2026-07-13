# `codebase` — GitHub repository settings for the whole monorepo (repo options, branch protection for
# main/develop, the staging/prod GitHub Environments). App-level (repo-global), a single instance tied
# to neither AWS env. The repository pre-exists and is IMPORTED into state, never created by Terraform.
locals {
  cfg = yamldecode(file("${path.module}/../../config.yaml"))
}

module "github_repo" {
  source = "../../modules/github_repo"

  repository_name        = local.cfg.project
  prod_reviewer_username = local.cfg.github_owner
}
