# Repo settings + branch protection + Environments (§13.7). The pre-existing repo is imported
# (runbook "repo" section); Terraform then owns its settings, including the private -> public flip
# (C-01). Staged-activation deviations from §13.7: review count 0 + no required_status_checks until
# CI exists (C-02, C-04 adds the contexts here); restrict_pushes omitted — GitHub push restriction
# also blocks PR merges, so an empty allowlist would make the branches unmergeable (C-08).
resource "github_repository" "this" {
  name         = var.repository_name
  description  = "AI assistant that answers short-term-rental guest questions from the host's guidebook — hola.host"
  homepage_url = "https://hola.host"
  visibility   = "public"

  has_issues   = true
  has_projects = false
  has_wiki     = false

  allow_merge_commit          = true # GitFlow release/hotfix merges keep the branch point (§13.7)
  allow_squash_merge          = true # feature/* -> develop: one commit per PR (§13.7)
  allow_rebase_merge          = false
  squash_merge_commit_title   = "PR_TITLE"
  squash_merge_commit_message = "PR_BODY"
  merge_commit_title          = "PR_TITLE"
  merge_commit_message        = "PR_BODY"
  delete_branch_on_merge      = true

  web_commit_signoff_required = false

  security_and_analysis {
    secret_scanning {
      status = "enabled"
    }
    secret_scanning_push_protection {
      status = "enabled"
    }
  }
}

# Dedicated resource — the github_repository.vulnerability_alerts argument is deprecated (§13.7).
resource "github_repository_vulnerability_alerts" "this" {
  repository = github_repository.this.name
}

resource "github_repository_dependabot_security_updates" "this" {
  repository = github_repository.this.name
  enabled    = true

  # Dependabot security updates require vulnerability alerts to be enabled first.
  depends_on = [github_repository_vulnerability_alerts.this]
}

resource "github_branch_protection" "main" {
  repository_id                   = github_repository.this.node_id
  pattern                         = "main"
  enforce_admins                  = true
  require_conversation_resolution = true
  allows_force_pushes             = false
  allows_deletions                = false

  required_pull_request_reviews {
    # Staged (C-02): 0 while the repo is single-maintainer — the author cannot approve their own
    # PR; raise to 1 (§13.7) once a second maintainer exists.
    required_approving_review_count = 0
    dismiss_stale_reviews           = true
  }
}

resource "github_branch_protection" "develop" {
  repository_id                   = github_repository.this.node_id
  pattern                         = "develop"
  enforce_admins                  = true
  require_conversation_resolution = true
  allows_force_pushes             = false
  allows_deletions                = false

  required_pull_request_reviews {
    required_approving_review_count = 0 # staged, see the main-branch note (C-02)
    dismiss_stale_reviews           = true
  }
}

data "github_user" "prod_reviewer" {
  username = var.prod_reviewer_username
}

# GitHub Environments (§13.7). OIDC deploy roles bind to them in C-08.
resource "github_repository_environment" "staging" {
  repository  = github_repository.this.name
  environment = "staging"
}

resource "github_repository_environment" "prod" {
  repository  = github_repository.this.name
  environment = "prod"
  wait_timer  = 0

  # Deployment approvals, unlike PR reviews, may be self-granted — workable single-maintainer.
  reviewers {
    users = [data.github_user.prod_reviewer.id]
  }
}
