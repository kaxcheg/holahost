# rag-documents — Environment Runbook

Per-service runbook (frame spec §"Инфраструктура сервиса — умолчания" → "Environmental runbook").
Every command below is meant to be copy-pasted as written from `holahost/services/rag-documents/`
unless noted otherwise.

## Topology

| Root | What it creates | Applied |
|---|---|---|
| `infra/common` | ECR repository `rag-documents` + lifecycle policy | once, shared by all environments |
| `infra/envs/staging` | DB password secret (Secrets Manager, value-less), CloudWatch log group, 5xx + p95-ingest alarms, SNS topic | once, before staging's first deploy |
| `infra/envs/prod` | same, for prod | once, before prod's first deploy |

Each environment is its own directory (not a Terraform workspace) — `infra/envs/dev/` holds only
an `.env`/`.env.example` (dev has no AWS resources at all, see below); `infra/envs/staging/` and
`infra/envs/prod/` each carry their own full Terraform root plus their own committed `.env` (no
secrets in it — see "Environment config files" below) and `terraform.tfvars` (currently a
placeholder `alert_email`, see that file).

State: S3 bucket `holahost-tfstate-common` with native locking (`use_lockfile = true`, Terraform
≥ 1.10, no DynamoDB). The bucket itself is a manual, one-time **platform** bootstrap step (frame
spec: created outside Terraform) — not part of this service's own roots.

**Platform dependency:** `infra/envs`'/the deploy pipelines' `terraform apply`/SSM Run Command
steps assume the platform-level `holahost/infra/` root (EC2 instance, security group, API Gateway,
CloudFront) already exists. It doesn't exist yet in this repo as of this writing — staging/prod
sections below are code-complete and `terraform validate`-clean, but not live-exercisable until
that separate platform work lands.

## Environment config files

The non-secret runtime settings (`EMBEDDING_MODEL`, chunk/search tuning, rate limits, `JWKS_URL`/
`EXPECTED_*`, `POSTGRES_USER`/`POSTGRES_DB`) live in `infra/envs/<env>/.env`, one per environment —
never the DB password or `DATABASE_URL` themselves. `scripts/bootstrap.py` only fetches the bare
password from Secrets Manager at container startup, before the app's `Settings` is even
constructed; `Settings` itself assembles `database_url` (a `@computed_field`, built via
`PostgresDsn`) from `postgres_user`/`postgres_password`/`postgres_db`/`postgres_host`/
`postgres_port` — the last two default to the fixed `postgres`/5432 convention, matching
`docker-compose.yml`'s `postgres` service, and aren't set in `.env`. `dev/.env` is a gitignored
local copy of `dev/.env.example` (per-
developer, per frame spec's `.env.dev` convention); `staging/.env` and `prod/.env` are committed
directly (no secrets in them) — nothing to copy or generate for those two. The one running compose
manifest (`docker-compose.yml`, service root) reads whichever folder `ENV` points at
(`env_file: ["infra/envs/${ENV:?...}/.env"]`, mandatory, no fallback) — same name the selected
`.env` file's own `ENV=` line carries (read by `Settings.env` once injected into the container),
not a collision: Compose resolves its `${ENV}` from the invoking shell before any container
starts, purely to pick which file to load — `make dev-up` exports `ENV=dev` (from `infra/envs/
dev/.env` itself); the deploy pipeline exports `ENV=staging`/`prod` explicitly when it runs the
same compose file on the instance.

## Prerequisites

Tool versions are pinned in the repo-root `.tool-versions` (single source for local dev, Docker,
and CI): Python 3.12, Poetry 2.2.1, Terraform 1.10+. Also needed: Docker + Docker Compose v2, AWS
CLI v2 (staging/prod only).

---

## dev

Local stack only — no AWS account, no Terraform, per frame spec's dev workflow.

**1. Deploy from scratch**
```bash
docker network create backbone            # once per machine
cp infra/envs/dev/.env.example infra/envs/dev/.env
make dev-up                                # docker build, then docker compose up -d
make migrate-dev                           # alembic upgrade head against the compose Postgres
curl http://localhost:8080/health          # -> {"status":"ok"}
```

**2. Check**
```bash
curl http://localhost:8080/health
```
Profile operation (frame spec §11 "Проверить" delta — exercise create → search → delete):
```bash
curl -sX POST http://localhost:8080/api/rag-documents/documents \
  -H "Authorization: Bearer <token>" -H "X-Request-ID: manual-check-1" \
  -F file=@/path/to/doc.pdf -F name="check doc"
# -> {"document_id": "...", ...}; then search that id, then DELETE it.
```
Logs: `make dev-logs` (== `docker compose logs -f`); grep for `op_completed` (per-request
completion event, §8.7) and `startup_completed` (model load + migration readiness at boot).

**3. Update**
```bash
make dev-down
make dev-up          # rebuilds the image, recreates the api container
make migrate-dev      # re-run — Alembic is idempotent (no-ops if already at head)
```

**4. Rollback**
No versioned releases in dev — `git checkout` the previous commit and repeat "Update" above. If
schema state is suspect, `make dev-down-v` (wipes the Postgres volume) and start from scratch.

**Recreate dependencies from scratch:**
```bash
make dev-down-v      # drops pgdata AND model-cache volumes
make dev-up
make migrate-dev
```
(The model re-downloads on next boot if `model-cache` was wiped — watch `startup_completed` for
timing.)

**Get a token — blocked, stub only.** Per the frame spec, until `auth` is built, dev tokens come
from a platform-level script `infra/scripts/mint-dev-token.py` (shared by every service, lives
under `holahost/infra/`). Neither that script nor `holahost/infra/` exists yet in this repo, and
building it is out of this ticket batch's scope (deferred — see
`.build-state/R-25-.../clarifications.md` "Dev JWT minting — deferred"). Until it lands, there is
no working command for this step; construct a token manually against `JWKS_URL`/`EXPECTED_*` in
`infra/envs/dev/.env` if you need one for manual testing.

---

## staging

**1. Deploy from scratch**
```bash
# Platform (once, by whoever owns platform infra — not this service):
#   terraform apply   (in holahost/infra/)

terraform -chdir=infra/common init && terraform -chdir=infra/common apply
terraform -chdir=infra/envs/staging init && terraform -chdir=infra/envs/staging apply
# alert_email comes from infra/envs/staging/terraform.tfvars (auto-loaded) — currently a
# placeholder, see that file's TODO.

# Fill the DB password (Secrets Manager creates the secret value-less by design). Value is a
# bare password, not a connection string — both `postgres` (its own init) and the app pick it
# up automatically on the next deploy/restart, nothing else to configure:
aws secretsmanager put-secret-value \
  --secret-id holahost/staging/rag-documents/db-password \
  --secret-string '<generated-password>'

# Confirm the SNS email subscription (check inbox for the confirmation link).

# First deploy is pipeline-driven, not manual: push to release/v* triggers
# .github/workflows/rag-documents-deploy-staging.yml (R-30).
```

**2. Check**
```bash
curl https://staging.hola.host/api/rag-documents/health
```
CloudWatch Logs group `/holahost/staging/rag-documents`: grep `op_completed`/`startup_completed`;
alarms `rag-documents-staging-5xx` / `rag-documents-staging-ingest-p95` in CloudWatch.

**3. Update**
Push to `release/v*` → `deploy-staging` pipeline: `terraform apply` → build+push image
(`git-<sha>` + `release-v<version>` tags) → SSM Run Command applies migrations **then** swaps the
container (`docker compose up -d` — recreate strategy, migrations always before code per frame
spec) → smoke, retried with a window (cold-start model download on first boot).

**4. Rollback**
Redeploy the previous image digest via SSM Run Command (`docker compose up -d` with `IMAGE=<prev
digest>`). If the last migration is irreversible, restore the DB from a snapshot rather than
`alembic downgrade` (frame spec: "откат данных — восстановлением БД, а не downgrade").

---

## prod

Identical to staging (own `infra/envs/prod/` root, `holahost/prod/rag-documents/db-password`,
`https://hola.host/api/rag-documents/health`, log group `/holahost/prod/rag-documents`), with two
differences per frame spec:

- Only promoted after a successful staging smoke.
- The `promote-prod` pipeline (R-31, triggered by tag `rag-documents/v*`) **resolves** the
  already-built `release-v<version>` image digest instead of rebuilding, and gates on a manual
  `environment: prod` approval before the SSM deploy step runs.

**1. Deploy from scratch:** same TF apply (`infra/envs/prod`)/secret-fill/SNS-confirm sequence as
staging. First deploy is pipeline-driven (tag push), not manual.
**2. Check:** `curl https://hola.host/api/rag-documents/health`; log group
`/holahost/prod/rag-documents`; alarms `rag-documents-prod-5xx` / `rag-documents-prod-ingest-p95`.
**3. Update:** tag `rag-documents/vYYYYMMDD.N` on the `main` merge commit → `promote-prod` pipeline.
**4. Rollback:** same as staging — redeploy previous digest via SSM; DB restore, not `downgrade`,
for irreversible migrations.

---

## Access

Staging/prod: GitHub OIDC (no long-lived AWS keys) — `deploy-staging`/`promote-prod` assume
per-environment IAM roles scoped to their trigger (`release/v*` branch / `rag-documents/v*` tag
respectively). Manual AWS console access follows the platform's standard IAM/MFA policy (out of
this service's own scope — see the platform frame spec).
