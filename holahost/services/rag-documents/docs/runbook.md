# rag-documents — environment runbook

How to stand this service up, check it, upgrade it and roll it back, per environment. Every command
is meant to be copy-pasted as written from `holahost/services/rag-documents/` unless noted.

## Topology

| Terraform root | What it creates | Applied |
|---|---|---|
| `infra/common` | ECR repository `rag-documents` + lifecycle policy | once, shared by all environments |
| `infra/envs/staging` | DB password secrets (Secrets Manager, value-less), CloudWatch log group, metric filters, 5xx and p95-ingest alarms, SNS topic | once, before staging's first deploy |
| `infra/envs/prod` | the same, for prod | once, before prod's first deploy |

Each environment is its own directory rather than a Terraform workspace: environments differ in
which resources exist and who may touch them, not only in variable values. `infra/envs/dev/` holds
no Terraform at all — dev has no AWS resources — only an `.env.example` and the local `.env` copied
from it.

State lives in the S3 bucket `holahost-tfstate-common` with native locking (`use_lockfile = true`,
Terraform ≥ 1.10, no DynamoDB table). The bucket is a one-time platform bootstrap created outside
Terraform, not part of this service's roots.

**Platform dependency.** The staging and prod procedures below assume the platform compute layer —
EC2 instance, security group, API Gateway, CloudFront — already exists. That layer is not part of
this repository; this service's roots call the shared modules in `holahost/infra/modules/` but
create no compute and no IAM roles of their own.

## Environment config files

| File | Holds | Committed |
|---|---|---|
| `infra/envs/<env>/.env` | non-secret runtime settings: `EMBEDDING_MODEL`, chunk and search tuning, rate limits, `JWKS_URL`/`EXPECTED_*`, `POSTGRES_USER`/`POSTGRES_DB` | staging and prod yes; dev no |
| `infra/envs/dev/.env.example` | the template dev's local `.env` is copied from | yes |
| Secrets Manager | both DB passwords | — |

Neither the DB password nor `DATABASE_URL` appears in any `.env`. At container startup
`app/scripts/bootstrap.py` fetches the bare password from Secrets Manager, and `Settings` assembles
`database_url` from it plus `postgres_user`/`postgres_db`; host and port default to the
`postgres`/5432 convention that `docker-compose.yml` provides.

One compose manifest serves every environment and reads whichever directory `ENV` points at
(`env_file: ["infra/envs/${ENV:?...}/.env"]`, mandatory, no fallback). Compose resolves `${ENV}`
from the invoking shell before any container starts, purely to choose the file: `make dev-up`
exports `ENV=dev`, and the pipeline exports `ENV=staging` or `ENV=prod` on the instance.

## Prerequisites

Tool versions are pinned in the repo-root `.tool-versions`, the single source for local development,
the Docker image and CI: Python 3.12, Poetry 2.2.1, Terraform 1.10+. Also required: Docker with
Compose v2, and AWS CLI v2 for staging and prod.

---

## dev

Local stack only — no AWS account, no Terraform.

**1. Deploy from scratch**

`dev-up` runs the same three steps, in the same order, as the staging and prod pipelines: migrations,
then app-role provisioning, then the container swap. `make migrate-dev` re-runs the first two on
their own (both are idempotent) after adding a migration.

```bash
docker network create backbone            # once per machine
cp infra/envs/dev/.env.example infra/envs/dev/.env
make dev-up
curl http://localhost:8080/api/rag-documents/health          # -> {"status":"ok"}
```

**2. Check**

```bash
curl http://localhost:8080/api/rag-documents/health

# profile operation: create -> search -> delete
curl -sX POST http://localhost:8080/api/rag-documents/documents \
  -H "Authorization: Bearer <token>" -H "X-Request-ID: manual-check-1" \
  -F file=@/path/to/doc.pdf -F name="check doc"
# -> {"document_id": "...", ...}; then search that id, then DELETE it.
```

Logs: `make dev-logs`. Grep for `op_completed` (one event per request) and `startup_completed`
(model load and migration readiness at boot).

**3. Update**

```bash
make dev-down
make dev-up          # rebuild, re-run migrations and provisioning, recreate the api container
```

**4. Rollback**

There are no versioned releases in dev: `git checkout` the previous commit and repeat "Update". If
the schema state is suspect, `make dev-down-v` wipes the Postgres volume and you start from scratch.

**Recreate dependencies from scratch**

```bash
make dev-down-v      # drops the pgdata AND model-cache volumes
make dev-up
```

The embedding model re-downloads on the next boot if `model-cache` was wiped — watch
`startup_completed` for how long that took.

**Get a token.** Until `auth` exists, mint one yourself against the `JWKS_URL` and `EXPECTED_*`
values in `infra/envs/dev/.env` and pass it as `Authorization: Bearer <token>`. The service
validates it offline, so any issuer matching that configuration works.

---

## staging

**1. Deploy from scratch**

```bash
terraform -chdir=infra/common init && terraform -chdir=infra/common apply
terraform -chdir=infra/envs/staging init && terraform -chdir=infra/envs/staging apply
# alert_email is read from infra/envs/staging/terraform.tfvars (auto-loaded).

# Fill BOTH DB passwords — Secrets Manager creates each secret value-less by design. The values are
# bare passwords, not connection strings, and they MUST differ from each other:
#
#   db-superuser-password  the `postgres` container's bootstrap superuser. Runs migrations and owns
#                          the tables. A superuser bypasses row-level security unconditionally.
#   db-password            the role the application authenticates as, created without
#                          SUPERUSER/BYPASSRLS by app/scripts/provision_app_role.py during deploy.
#
# Owner isolation rests entirely on RLS, so one value for both would hand that bypass to anything
# holding the application's credentials. The app refuses to start if it connects as a role that can
# bypass RLS.
aws secretsmanager put-secret-value \
  --secret-id holahost/staging/rag-documents/db-superuser-password \
  --secret-string '<generated-password-1>'
aws secretsmanager put-secret-value \
  --secret-id holahost/staging/rag-documents/db-password \
  --secret-string '<generated-password-2>'

# Confirm the SNS email subscription from the link sent to alert_email.
# The first deploy is pipeline-driven, not manual: a push to release/v* triggers
# .github/workflows/rag-documents-deploy-staging.yml.
```

**2. Check**

```bash
curl https://staging.hola.host/api/rag-documents/health
```

CloudWatch Logs group `/holahost/staging/rag-documents` — grep `op_completed` and
`startup_completed`. Alarms: `rag-documents-staging-5xx`, `rag-documents-staging-ingest-p95`.

**3. Update**

Push to `release/v*`. The `deploy-staging` pipeline runs `terraform apply`, builds and pushes the
image tagged `git-<sha>` only, then an SSM Run Command applies migrations, provisions the app role
and **then** swaps the container (`docker compose up -d`, recreate strategy — migrations always
precede code, so they must be backwards-compatible). The smoke check retries within a window,
because the model downloads on a cold start. Re-running the workflow on an unchanged commit is safe:
the build step reuses the digest already tagged `git-<sha>` instead of rebuilding.

The `release-v<version>` tag is not applied here. It is written later by `promote-prod`, onto the
digest that actually shipped: the ECR repository is immutable, and a release branch takes more than
one commit, so a tag derived from the branch could not be written twice.

**4. Rollback**

Redeploy the previous image digest via SSM Run Command (`docker compose up -d` with
`IMAGE=<previous digest>`). If the last migration is irreversible, restore the database from a
snapshot rather than running `alembic downgrade`.

**5. Rotate a DB password**

```bash
aws secretsmanager put-secret-value \
  --secret-id holahost/staging/rag-documents/db-password \
  --secret-string '<new-password>'
# then REDEPLOY — a restart is not enough.
```

The deploy's provisioning step (`app/scripts/provision_app_role.py`) is the only thing that applies
the new value to the Postgres role: the `postgres` image sets a password at initdb only, and
`pgdata` outlives every restart. Restarting `api` without redeploying changes only which password
the client offers, and every connection then fails to authenticate.

Rotating `db-superuser-password` is a larger operation. That role's password is likewise fixed at
initdb, so it needs an explicit `ALTER ROLE postgres PASSWORD` (via
`docker compose exec postgres psql`) **before** the secret is updated, or the next deploy loses its
own access.

---

## prod

Identical to staging — its own `infra/envs/prod/` root, both
`holahost/prod/rag-documents/db-password` and `holahost/prod/rag-documents/db-superuser-password`,
`https://hola.host/api/rag-documents/health`, log group `/holahost/prod/rag-documents` — with two
differences:

- Nothing is promoted before a successful staging smoke.
- The `promote-prod` pipeline, triggered by a `rag-documents/v*` tag, **resolves** the already-built
  image by the tagged commit's `git-<sha>` instead of rebuilding, and gates on a manual
  `environment: prod` approval before the SSM deploy step. After the prod smoke passes it tags that
  exact digest `release-v<version>`, so the version tag means "this shipped". Tagging a commit that
  `deploy-staging` never built fails the pipeline immediately, by design.

**1. Deploy from scratch:** the same apply / fill-secrets / confirm-SNS sequence as staging, against
`infra/envs/prod`. The first deploy is pipeline-driven (tag push), not manual.

**2. Check:** `curl https://hola.host/api/rag-documents/health`; log group
`/holahost/prod/rag-documents`; alarms `rag-documents-prod-5xx`, `rag-documents-prod-ingest-p95`.

**3. Update:** tag `rag-documents/vYYYYMMDD.N` on the `release/v*` commit that passed staging. Tag
the release-branch commit, not the `main` merge commit: a squash merge lands on `main` as a new
commit object whose sha never existed on the release branch, so no `git-<sha>` image was ever built
for it and the resolve above would find nothing. Merge the release branch into `main` as usual
afterwards.

**4. Rollback:** as in staging — redeploy the previous digest via SSM; restore the database rather
than running `downgrade` for irreversible migrations.

---

## Prerequisite outside this service's Terraform

The `api` container logs through Docker's `awslogs` driver straight into
`/holahost/<env>/rag-documents`. That needs **`logs:CreateLogStream` and `logs:PutLogEvents` on the
instance role**, which this service's Terraform cannot grant: `infra/envs/<env>` owns the log group,
the metric filters and the alarms, `infra/common` owns ECR, and neither owns compute or IAM. Those
are platform-level, like the `github-actions-rag-documents-*` roles the pipelines assume.

Until the permission exists the container **will not start** on staging or prod — Docker refuses to
run a container whose log driver cannot attach. That failure is deliberate and loud at deploy time,
rather than a service that runs while its observability stack reads as healthy over a log group
receiving nothing.

Symptom: `docker compose up -d` fails on the instance with a `ResourceNotFoundException` or
`AccessDeniedException` from the driver, visible in the SSM command output the deploy step already
surfaces.

## Access

Staging and prod use GitHub OIDC — no long-lived AWS keys. `deploy-staging` and `promote-prod`
assume per-environment IAM roles scoped to their trigger (the `release/v*` branch and the
`rag-documents/v*` tag respectively). Manual console access follows the platform's IAM and MFA
policy, which is outside this service's scope.
