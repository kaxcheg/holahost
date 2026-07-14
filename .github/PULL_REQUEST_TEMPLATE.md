## What was done
<!-- one-line bullets; reference spec §X.Y where applicable -->

## Why
<!-- one-two lines of context: why now, what pain it solves -->

## How to verify
<!-- step-by-step: make commands, expected behavior, URLs -->

## Branch / merge target
- [ ] Source branch conforms to §13.0 (`feature/`, `bugfix/`, `refactor/`, `chore/`, `docs/`, `test/`, `release/v*`, `hotfix/v*`)
- [ ] Target branch is correct: feature/bugfix/refactor/chore/docs/test → `develop`; release/v* and hotfix/v* → `main` + back-merge to `develop`

## DB / API / breaking changes
- [ ] Alembic migrations are backward-compatible (add nullable → switch code → drop old; §13.5)
- [ ] HTTP API changes are documented in spec §5
- [ ] DB schema changes are documented in spec §4
- [ ] Frontend-breaking change is flagged with a `BREAKING CHANGE:` commit footer

## Checklist
- [ ] pre-commit passed locally
- [ ] CI green
- [ ] If the spec changes — `holahost/services/lead-capture/docs/lead_capture_spec.md` is updated in this PR
