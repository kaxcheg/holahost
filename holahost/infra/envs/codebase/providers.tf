# Auth: GITHUB_TOKEN env var — a fine-grained PAT with Administration + Environments read/write on the
# repo (runbook "codebase" section). Owner comes from config.yaml (single source).
provider "github" {
  owner = local.cfg.github_owner
}
