# GitHub repo settings root (I-14). A separate root/state (holahost-tfstate-repo): the repository
# is a single instance tied to neither AWS env — see infra/modules/README.md.
locals {
  cfg = yamldecode(file("${path.module}/../../config.yaml"))
}

module "github_repo" {
  source = "../../modules/github_repo"

  repository_name        = local.cfg.project
  prod_reviewer_username = local.cfg.github_owner
}
