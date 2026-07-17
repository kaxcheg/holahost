## What was done
<!-- one-line bullets -->

## Why
<!-- one-two lines of context: why now, what pain it solves -->

## How to verify
<!-- step-by-step: commands, expected behavior, URLs -->

## Branch / merge target
- [ ] Source branch conforms to CONTRIBUTING (`feature/`, `bugfix/`, `refactor/`, `chore/`, `docs/`, `test/`, `release/v*`, `hotfix/v*`)
- [ ] Target branch is correct: feature/bugfix/refactor/chore/docs/test → `develop`; release/v* and hotfix/v* → `main` + back-merge to `develop`

## DB / API / breaking changes
- [ ] DB migrations are backward-compatible
- [ ] HTTP API / DB schema changes are documented in the affected service's spec
- [ ] Breaking changes are flagged with a `BREAKING CHANGE:` commit footer

## Checklist
- [ ] pre-commit passed locally
- [ ] CI green
- [ ] If a spec changes — it is updated in this PR
