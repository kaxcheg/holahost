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

> A `pgdata` volume created before the bootstrap-superuser split must be wiped once
> (`make dev-down-v`). The `postgres` image runs initdb only on an empty volume, so an older
> volume still has the app's own name as its superuser and no `postgres` role at all — the
> deploy's elevated steps would fail with `role "postgres" does not exist`. Nothing to migrate
> in dev; recreate it.

`dev-up` runs the same three steps, in the same order, that the staging/prod pipeline runs via
SSM: migrations, then app-role provisioning, then the container swap. `make migrate-dev` remains
available on its own to re-run just the first two (both are idempotent) after adding a migration.

```bash
docker network create backbone            # once per machine
cp infra/envs/dev/.env.example infra/envs/dev/.env
make dev-up          # build, then migrations + app-role provisioning, then compose up -d
curl http://localhost:8080/api/rag-documents/health          # -> {"status":"ok"}
```

**2. Check**
```bash
curl http://localhost:8080/api/rag-documents/health
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
make dev-up          # rebuilds, re-runs migrations + provisioning, recreates the api container
```

**4. Rollback**
No versioned releases in dev — `git checkout` the previous commit and repeat "Update" above. If
schema state is suspect, `make dev-down-v` (wipes the Postgres volume) and start from scratch.

**Recreate dependencies from scratch:**
```bash
make dev-down-v      # drops pgdata AND model-cache volumes
make dev-up
```
(The model re-downloads on next boot if `model-cache` was wiped — watch `startup_completed` for
timing.)

**Get a token — blocked, stub only.** Per the frame spec, until `auth` is built, dev tokens come
from a platform-level script `infra/scripts/mint-dev-token.py` (shared by every service, lives
under `holahost/infra/`). Neither that script nor `holahost/infra/` exists yet in this repo.
Until it lands, there is
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

# Fill BOTH DB passwords (Secrets Manager creates each secret value-less by design). Values are
# bare passwords, not connection strings, and they MUST be different from each other:
#
#   db-superuser-password  the `postgres` container's own bootstrap superuser. Runs migrations,
#                          owns the tables. A superuser bypasses row-level security
#                          unconditionally.
#   db-password            the role the application authenticates as — created without
#                          SUPERUSER/BYPASSRLS by scripts/provision_app_role.py during deploy.
#
# Owner isolation in this service is enforced only by RLS, so reusing one value for both would
# hand the bypass to anything holding the app's credentials. The app refuses to start if it ever
# ends up connecting as a role that can bypass RLS (scripts/bootstrap.py).
aws secretsmanager put-secret-value \
  --secret-id holahost/staging/rag-documents/db-superuser-password \
  --secret-string '<generated-password-1>'
aws secretsmanager put-secret-value \
  --secret-id holahost/staging/rag-documents/db-password \
  --secret-string '<generated-password-2>'

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
Push to `release/v*` → `deploy-staging` pipeline: `terraform apply` → build+push image (`git-<sha>`
only — the `release-v<version>` tag is applied later, by `promote-prod`, onto the digest that
actually ships; the ECR repo is immutable, and a release branch takes more than one commit) → SSM
Run Command applies migrations, provisions the app role, **then** swaps the container (`docker
compose up -d` — recreate strategy, migrations always before code per frame spec) → smoke, retried
with a window (cold-start model download on first boot). Re-running the workflow on an unchanged
commit is safe: the build step reuses the digest already tagged `git-<sha>` instead of rebuilding.

**5. Rotate a DB password**
```bash
aws secretsmanager put-secret-value \
  --secret-id holahost/staging/rag-documents/db-password \
  --secret-string '<new-password>'
# then REDEPLOY — a restart is not enough.
```
The deploy's provisioning step (`scripts/provision_app_role.py`) is the only thing that applies the
new value to the Postgres role: the `postgres` image sets a password at initdb only, and `pgdata`
outlives every restart. Restarting `api` without redeploying changes only which password the client
offers, and every connection then fails to authenticate. Rotating `db-superuser-password` is a
bigger operation — the bootstrap role's password is likewise fixed at initdb, so it needs an
explicit `ALTER ROLE postgres PASSWORD` (via `docker compose exec postgres psql`) *before* the
secret is updated, or the next deploy loses its own access.

**4. Rollback**
Redeploy the previous image digest via SSM Run Command (`docker compose up -d` with `IMAGE=<prev
digest>`). If the last migration is irreversible, restore the DB from a snapshot rather than
`alembic downgrade` (frame spec: "откат данных — восстановлением БД, а не downgrade").

---

## prod

Identical to staging (own `infra/envs/prod/` root, both `holahost/prod/rag-documents/db-password`
and `holahost/prod/rag-documents/db-superuser-password`,
`https://hola.host/api/rag-documents/health`, log group `/holahost/prod/rag-documents`), with two
differences per frame spec:

- Only promoted after a successful staging smoke.
- The `promote-prod` pipeline (R-31, triggered by tag `rag-documents/v*`) **resolves** the
  already-built image by the tagged commit's own `git-<sha>` tag instead of rebuilding, and gates
  on a manual `environment: prod` approval before the SSM deploy step runs. After the prod smoke
  passes it tags that exact digest `release-v<version>` — so the version tag means "this shipped",
  and it is written once, which is what an immutable repository allows. Tagging a commit that
  `deploy-staging` never built fails the pipeline immediately, by design.

**1. Deploy from scratch:** same TF apply (`infra/envs/prod`)/secret-fill/SNS-confirm sequence as
staging. First deploy is pipeline-driven (tag push), not manual.
**2. Check:** `curl https://hola.host/api/rag-documents/health`; log group
`/holahost/prod/rag-documents`; alarms `rag-documents-prod-5xx` / `rag-documents-prod-ingest-p95`.
**3. Update:** tag `rag-documents/vYYYYMMDD.N` on the `release/v*` commit that passed staging →
`promote-prod` pipeline. Not on the `main` merge commit: a squash-merged `release/v*` lands on
`main` as a new commit object with a sha that never existed on the release branch, so no
`git-<sha>` image was ever built for it and the resolve described above would find nothing. Merge
the release branch into `main` as usual afterwards.
**4. Rollback:** same as staging — redeploy previous digest via SSM; DB restore, not `downgrade`,
for irreversible migrations.

---

## Prerequisite outside this service's terraform

The `api` container logs through Docker's `awslogs` driver straight into
`/holahost/<env>/rag-documents` (docker-compose.yml). That needs **`logs:CreateLogStream`
and `logs:PutLogEvents` on the instance role**, and this service's terraform cannot grant
it: `infra/envs/<env>` owns the log group, the metric filters and the alarms, `infra/common`
owns ECR — no compute, no instance profile, no IAM role. Those are platform-level, same as
the `github-actions-rag-documents-*` roles both pipelines assume.

Until the permission exists the container **will not start** on staging or prod: Docker
refuses to run a container whose log driver cannot attach. That is the intended failure —
loud at deploy time, rather than a service that runs while its whole observability stack
(ten metric filters, four alarms, the dashboard) sits on a log group receiving nothing and
reads as healthy, since `treat_missing_data = "notBreaching"` cannot tell silence from calm.

Symptom if it is missing: `docker compose up -d` fails on the instance with a
`ResourceNotFoundException` or `AccessDeniedException` from the driver, visible in the SSM
command output the deploy step already surfaces.

---

## Access

Staging/prod: GitHub OIDC (no long-lived AWS keys) — `deploy-staging`/`promote-prod` assume
per-environment IAM roles scoped to their trigger (`release/v*` branch / `rag-documents/v*` tag
respectively). Manual AWS console access follows the platform's standard IAM/MFA policy (out of
this service's own scope — see the platform frame spec).
