# Auth: GITHUB_TOKEN env var — a fine-grained PAT with Administration + Environments read/write on
# the repo (runbook "repo" section). Owner comes from config.yaml (single source, §10.9).
provider "github" {
  owner = local.cfg.github_owner
}
