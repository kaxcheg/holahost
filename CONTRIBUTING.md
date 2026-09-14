# Contributing to Holahost

Conventions for this **microservice monorepo**: backend microservices (`holahost/services/<svc>/`),
each a container on the shared `backbone` Docker network, talking over HTTP; shared libraries
(`holahost/libs/`); and the Terraform modules their own roots call (`holahost/infra/modules/`).

**Each microservice is a self-contained deployable** — it owns its ECR repo, Terraform roots (one
directory per environment) and CI/CD pipelines for local dev / staging / prod, with its own version
tag `<svc>/vYYYYMMDD.N`. The contract every service must satisfy (container `:8080`,
`GET <API_BASE_URL>/health`, offline JWT validation, OpenAPI, independent deploy) is in
[`holahost/README.md`](holahost/README.md).

That file is the source of truth for architecture; this one is the day-to-day summary. Toolchain
setup is in [`README.md`](README.md); operating a service is in its own `docs/runbook.md`.

## Branching (GitFlow)

Long-lived: `main` (production-ready) and `develop` (integration). Default branch is `develop`.

| Type | From | Back into | Purpose |
|---|---|---|---|
| `feature/[<service>/]<slug>` | `develop` | `develop` | new feature |
| `bugfix/[<service>/]<slug>` | `develop` | `develop` | non-urgent bug fix |
| `refactor/…` `chore/…` `docs/…` `test/…` (`[<service>/]<slug>`) | `develop` | `develop` | other changes |
| `release/v<version>` | `develop` | `main` **and** back-merge to `develop` | release freeze before prod |
| `hotfix/v<version>` | `main` | `main` **and** back-merge to `develop` | urgent prod fix |

`<slug>` is kebab-case, ≤ 40 chars; short-lived branches live ≤ 3 days. **A branch developing a
microservice carries its name** as the `<service>` segment (e.g. `feature/auth/<slug>`); shared-part
branches omit it (`feature/<slug>`). The type prefix stays first, so prefix-based branch protection
is unaffected.

**Deploy roles:** `develop` — integration + CI, **no deploy**; `release/v*` — deploys the touched units
to **staging**; `main` — prod is promoted per unit by a unit-scoped tag `<unit>/v<version>` on the
`release/*` / `hotfix/*` merge commit. **Versioning is per unit** (`<unit>/vYYYYMMDD.N`, UTC date + daily
sequence) — there is no single repo-wide version.

## Commits (Conventional Commits)

`<type>(<scope>)?: <subject>` — `<type>` ∈ `feat | fix | chore | refactor | docs | test | build | ci`;
`<scope>` (optional) names the affected unit/area (`auth`, `frontend`, `infra`);
subject ≤ 72 chars, imperative, no trailing period; body (optional) after a blank line, ≤ 100 chars/line;
breaking changes: `!` after `<type>` or a `BREAKING CHANGE:` footer. The `commit-msg` hook
(`conventional-pre-commit`) enforces the format and allowed types.

## Merge strategy

Pick by source branch:

| PR | Strategy |
|---|---|
| `feature/` `bugfix/` `refactor/` `chore/` `docs/` `test/` → `develop` | **squash-and-merge** (PR title becomes the commit subject — Conventional Commits) |
| `release/v*` → `main` | **merge commit**, then tag the promoted units `<unit>/v<version>` |
| `release/v*` → `develop` (back-merge) | **merge commit** |
| `hotfix/v*` → `main` | **merge commit** + tag `<unit>/v<version>` |
| `hotfix/v*` → `develop` (back-merge) | **merge commit** |

Direct pushes to `main` / `develop` are blocked — everything lands via PR. Head branches auto-delete on
merge (`main` / `develop` / `release/*` persist).

## Code style

**Python** (`holahost/services/<svc>/backend/`, `holahost/libs/<lib>/`): `snake_case`
modules/files/functions/variables; `PascalCase` classes and type aliases; `UPPER_SNAKE_CASE`
constants; leading-underscore privacy marker. **Postgres**: plural `snake_case` tables; `snake_case`
columns; PK `id`; FK `<table_singular>_id`; indexes `idx_<table>_<col>…`; Alembic migrations
`YYYYMMDD_HHMM_<slug>.py`. Formatting and linting are hook-enforced (ruff) — don't hand-format
against them.

## Tooling & hooks

One-time after cloning: `make hooks-install` (installs the `pre-commit` + `commit-msg` git hooks). The
set (`.pre-commit-config.yaml`): ruff check `--fix` + format, mypy (strict) and import-linter — each
run once per Python package in the repo, in that package's own venv — plus
`conventional-pre-commit`, gitleaks, and the pre-commit-hooks basics (whitespace / EOF / yaml / json
/ merge-conflict / large files > 1 MB).

- Bypassing hooks (`git commit --no-verify`) is forbidden by policy; CI re-runs the same checks, per
  package: each pipeline runs the generic hooks over its changed files and ruff, mypy and
  import-linter on its own package only. A library change re-runs every service's pipeline, and the
  libraries themselves are gated by `libs-ci`.
- `make ci-local`, from a service directory, runs the CI-parity suite locally (hooks + the full test
  suite + the OpenAPI contract check) — use it before pushing.
- Every PR fills the template (`.github/PULL_REQUEST_TEMPLATE.md`); an empty section is a review finding.
