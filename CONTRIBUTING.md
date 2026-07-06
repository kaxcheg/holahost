# Contributing to hola.host

Conventions for working in this repository. They mirror the spec
([`docs/hola_host_spec.md`](docs/hola_host_spec.md) §13) — the spec is the source of truth; this
file is the day-to-day summary. Toolchain setup lives in [`README.md`](README.md) and
[`infra/README.md`](infra/README.md).

## Branching (GitFlow)

Long-lived branches: `main` (production-ready; every merge is tagged and promotes to prod) and
`develop` (integration; staging auto-deploys from it). Default branch is `develop`.

| Type | Branches from | Merges back into | Purpose |
|---|---|---|---|
| `feature/<slug>` | `develop` | `develop` | new feature |
| `bugfix/<slug>` | `develop` | `develop` | non-urgent bug fix |
| `refactor/<slug>` / `chore/<slug>` / `docs/<slug>` / `test/<slug>` | `develop` | `develop` | other non-feature changes |
| `release/v<version>` | `develop` | `main` **and** back-merge into `develop` | QA / release freeze before prod |
| `hotfix/v<version>` | `main` | `main` **and** back-merge into `develop` | urgent prod fix |

`<slug>` is kebab-case, ≤ 40 characters. Short-lived branches live ≤ 3 days.

**Versioning:** `vYYYYMMDD.N` — calendar version (UTC date + sequence number within the day), e.g.
`v20260603.1`. Created as an annotated git tag on the `release/v*` / `hotfix/v*` merge commit in
`main`; the tag triggers the prod promotion (spec §13.5).

## Commits (Conventional Commits)

Format: `<type>(<scope>)?: <subject>`

- `<type>` ∈ `feat | fix | chore | refactor | docs | test | build | ci`;
- subject ≤ 72 characters, imperative mood, no trailing period;
- body (optional) after a blank line, ≤ 100 characters per line;
- breaking changes: `!` after `<type>` or a `BREAKING CHANGE: <description>` footer.

Examples:

```
feat(api): add /api/ingest/upload endpoint
fix(captures): rollback Lead on Resend timeout
refactor(domain)!: rename Guidebook.id field
```

The `commit-msg` hook (`conventional-pre-commit`) enforces the format and the allowed types.
Length limits (72 / 100) are convention enforced in review — the hook does not measure them.

## Merge strategy

Repository merge settings are Terraform-managed (`infra/modules/github_repo/`, spec §13.7).
Pick the strategy by source branch:

| PR | Strategy |
|---|---|
| `feature/` `bugfix/` `refactor/` `chore/` `docs/` `test/` → `develop` | **squash-and-merge** (one commit per PR; the PR title becomes the commit subject — it must follow Conventional Commits) |
| `release/v*` → `main` | **create-merge-commit**, then tag `v<version>` on the merge commit |
| `release/v*` → `develop` (back-merge) | **create-merge-commit** |
| `hotfix/v*` → `main` | **create-merge-commit** + tag `v<version>` |
| `hotfix/v*` → `develop` (back-merge) | **create-merge-commit** |

Direct pushes to `main` / `develop` are blocked — everything lands via PR. Head branches are
auto-deleted on merge (`main` / `develop` / `release/*` persist; release branches are removed
manually after a successful prod promote + back-merge).

## Code style

**Python** (`backend/`): modules, files, functions, variables — `snake_case`; classes and type
aliases — `PascalCase`; constants — `UPPER_SNAKE_CASE`; privacy marker — leading underscore
(`_internal_helper`). Domain entities / value objects follow the spec §7 names without
abbreviations (`GuidebookId`, not `GbId`).

**TypeScript** (`frontend/`): files — `kebab-case.ts`; variables, functions — `camelCase`; types,
interfaces, components — `PascalCase`; env-derived constants — `UPPER_SNAKE_CASE`.

**Postgres**: tables — plural `snake_case` (`leads`, `guidebooks`); columns — `snake_case`;
PK — `id`; FK — `<referenced_table_singular>_id`; indexes — `idx_<table>_<col>[_<col>...]`;
Alembic migrations — `YYYYMMDD_HHMM_<slug>.py` (e.g. `20250601_1200_add_guidebook_name_column.py`).

Formatting and linting are enforced by the hooks below (ruff for Python, biome for TypeScript) —
don't hand-format against them.

## Tooling & hooks

One-time after cloning:

```bash
make hooks-install   # installs the git hooks (pre-commit + commit-msg stages)
```

The hook set (`.pre-commit-config.yaml`, spec §13.3): ruff check `--fix` + ruff format, mypy
(strict), import-linter (clean-architecture contract), biome check `--write`, tsc `--noEmit`,
validate-sample-messages (docs/sample_messages.json shape guard, C-10b),
conventional-pre-commit, gitleaks, and the pre-commit-hooks basics (whitespace / EOF / yaml / json /
merge-conflict / large files > 1 MB).

- Bypassing hooks (`git commit --no-verify`) is forbidden by policy; CI re-runs the full set and
  blocks the PR on any mismatch.
- `make ci-local` runs the full CI-parity suite locally (hooks + backend tests + frontend tests +
  build) — use it before pushing when working offline.
- Every PR must fill the template (`.github/PULL_REQUEST_TEMPLATE.md`); an empty section is a
  review finding.
