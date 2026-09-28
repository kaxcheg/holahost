# llm-client — environment runbook

How to stand this service up, check it, upgrade it and roll it back, per environment. Every command
is meant to be copy-pasted as written from `holahost/services/llm-client/` unless noted.

## Topology

| Terraform root | What it creates | Applied |
|---|---|---|
| `infra/common` | ECR repository `llm-client` + lifecycle policy | once, shared by all environments |
| `infra/envs/staging` | secrets (Secrets Manager, value-less): both DB passwords and one key per provider of the registry; CloudWatch log group, metric filters, alarms (5xx, generation p95, success rate, upstream share, downgraded share, provider budgets), dashboard, saved Logs Insights queries, SNS topic | once, before staging's first deploy |
| `infra/envs/prod` | the same, for prod | once, before prod's first deploy |

Each environment is its own directory rather than a Terraform workspace: environments differ in
which resources exist and who may touch them, not only in variable values. `infra/envs/dev/` holds
no Terraform at all — dev has no AWS resources — only an `.env.example` and the local `.env` copied
from it.

The provider-key secrets are read off `backend/app/config/registry.yaml`, one per `api_key_ref`, so
adding a provider to the registry adds its secret at the next `terraform apply`. A provider disabled
in the registry keeps its secret; a provider whose block is **removed** from the registry loses it at
the next apply — immediately on staging (no recovery window), within 30 days recoverably on prod.
Disable a provider rather than delete it unless its key is meant to go.

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
| `infra/envs/<env>/.env` | non-secret runtime settings: budget ceilings, rate limits, the idempotency-key lifetime, `JWKS_URL`/`EXPECTED_*`, `POSTGRES_USER`/`POSTGRES_DB`, `AWS_REGION` | staging and prod yes; dev no |
| `infra/envs/dev/.env.example` | the template dev's local `.env` is copied from — including a placeholder `ANTHROPIC_API_KEY` | yes |
| Secrets Manager | both DB passwords and every provider key | — |

Neither a password nor a provider key appears in a staging or prod `.env`. At container startup
`app/scripts/bootstrap.py` fetches the DB password and the key of every enabled provider from
Secrets Manager (`holahost/<env>/llm-client/<name>`), and hands each key on through the variable
named after its reference (`anthropic-api-key` → `ANTHROPIC_API_KEY`); a missing one stops the
startup. `Settings` assembles `database_url` from the password plus `postgres_user`/`postgres_db`.

The environment's Terraform reads the same `.env`: the budget alarms compare against the
`BUDGET_CAP_PROVIDER_*` the service enforces, so a ceiling changed there moves its alarm at the next
`terraform apply`.

One compose manifest serves every environment and reads whichever directory `ENV` points at
(`env_file: ["infra/envs/${ENV:?...}/.env"]`, mandatory, no fallback). `make dev-up` exports
`ENV=dev`; the pipeline exports `ENV=staging` or `ENV=prod` on the instance.

## Prerequisites

Tool versions are pinned in the repo-root `.tool-versions`, the single source for local development,
the Docker image and CI: Python 3.12, Poetry 2.2.1, Terraform 1.10+. Also required: Docker with
Compose v2, and AWS CLI v2 for staging and prod.

---

## dev

Local stack only — no AWS account, no Terraform.

**1. Deploy from scratch**

`dev-up` runs the same three steps, in the same order, as the staging and prod pipelines: migrations,
then app-role provisioning, then the container swap.

```bash
docker network create backbone            # once per machine
cp infra/envs/dev/.env.example infra/envs/dev/.env
# The service refuses to start without a key for every enabled provider: the placeholder in
# ANTHROPIC_API_KEY starts it, and a real key is needed only to generate.
make dev-up
curl http://localhost:8080/api/llm-client/health          # -> {"status":"ok"}
```

**2. Check**

```bash
curl http://localhost:8080/api/llm-client/health

# profile operation: one short generation on the cheapest alias — it costs real money
curl -sX POST http://localhost:8080/api/llm-client/generate \
  -H "Authorization: Bearer <token>" -H "X-Request-ID: manual-check-1" \
  -H "Content-Type: application/json" \
  -d '{"model": "fast", "messages": [{"role": "user", "content": "Say OK."}], "max_tokens": 5}'
# -> {"text": "...", "usage": {...}, "provider": "anthropic", "model": "claude-haiku-4-5", ...}
```

Logs: `make dev-logs`. Grep for `op_completed` (one event per request, with the tokens, attempts and
the actual model) and `startup_completed`.

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
make dev-down-v      # drops the pgdata volume — the usage log, and with it today's budget spend
make dev-up
```

**Get a token.** Until `auth` exists, mint one yourself against the `JWKS_URL` and `EXPECTED_*`
values in `infra/envs/dev/.env` (`aud` must contain `llm-client`) and pass it as
`Authorization: Bearer <token>`. The service validates it offline, so any issuer matching that
configuration works.

---

## staging

**1. Deploy from scratch**

```bash
terraform -chdir=infra/common init && terraform -chdir=infra/common apply
terraform -chdir=infra/envs/staging init && terraform -chdir=infra/envs/staging apply
# alert_email is read from infra/envs/staging/terraform.tfvars (auto-loaded).

# Fill every secret — Secrets Manager creates them value-less by design.
#
#   db-superuser-password  the `postgres` container's bootstrap superuser: runs migrations and owns
#                          the table. Never the running app.
#   db-password            the role the application authenticates as, created with DML grants only
#                          by app/scripts/provision_app_role.py during deploy.
#   anthropic-api-key      the provider's key; one such secret per `api_key_ref` in the registry.
#
# The two DB passwords MUST differ: one value for both would hand the DDL rights to anything holding
# the application's credentials.
aws secretsmanager put-secret-value \
  --secret-id holahost/staging/llm-client/db-superuser-password \
  --secret-string '<generated-password-1>'
aws secretsmanager put-secret-value \
  --secret-id holahost/staging/llm-client/db-password \
  --secret-string '<generated-password-2>'
aws secretsmanager put-secret-value \
  --secret-id holahost/staging/llm-client/anthropic-api-key \
  --secret-string '<the vendor key for staging>'

# Confirm the SNS email subscription from the link sent to alert_email.
```

The first rollout is the `deploy-staging` pipeline (a push to `release/v*`, see "Update") once its
OIDC role exists; until then roll out by hand, as below — the same steps the pipeline runs.

**Rolling out by hand**

Build and push the image from a checkout of the commit (the ECR URL is `infra/common`'s
`repository_url` output):

```bash
make ci-image                                   # builds llm-client:ci
aws ecr get-login-password | docker login --username AWS --password-stdin <registry>
docker tag llm-client:ci <repository_url>:git-$(git rev-parse HEAD)
docker push <repository_url>:git-$(git rev-parse HEAD)
```

Copy `docker-compose.yml` and `infra/envs/staging/.env` to `/opt/services/llm-client/` on the
instance (same relative paths), then, in an SSM session there:

```bash
cd /opt/services/llm-client
export IMAGE=<repository_url>@<digest>
export POSTGRES_SUPERUSER_PASSWORD=$(aws secretsmanager get-secret-value \
  --secret-id holahost/staging/llm-client/db-superuser-password --query SecretString --output text)
PGPW=$(aws secretsmanager get-secret-value \
  --secret-id holahost/staging/llm-client/db-password --query SecretString --output text)
docker compose --env-file infra/envs/staging/.env run --rm \
  -e "POSTGRES_SUPERUSER_PASSWORD=$POSTGRES_SUPERUSER_PASSWORD" api python -m alembic upgrade head
docker compose --env-file infra/envs/staging/.env run --rm \
  -e "POSTGRES_SUPERUSER_PASSWORD=$POSTGRES_SUPERUSER_PASSWORD" -e "POSTGRES_PASSWORD=$PGPW" \
  api python -m scripts.provision_app_role
docker compose --env-file infra/envs/staging/.env up -d
```

`--env-file` is what gives compose `ENV` (the `.env` carries it), and `IMAGE` and
`POSTGRES_SUPERUSER_PASSWORD` are required by the compose file itself: without them every compose
command stops before doing anything.

**2. Check**

```bash
curl https://staging.hola.host/api/llm-client/health
```

Then one paid generation, as in dev's Check, against `https://staging.hola.host/api/llm-client/generate`
with a token for the staging issuer — once. It spends money: do not loop it.

CloudWatch Logs group `/holahost/staging/llm-client` — grep `op_completed` and `startup_completed`;
the saved queries `llm-client-staging/*` (spend by caller, unique callers, requested vs actual model);
the dashboard `llm-client-staging`. Alarms: `llm-client-staging-5xx`, `-generate-p95`,
`-generate-success-rate`, `-upstream-share`, `-downgraded-share`, `-budget-<provider>-{input,output}`.

**3. Update**

Push to `release/v*`. The `deploy-staging` pipeline runs `terraform apply`, builds and pushes the
image tagged `git-<sha>` only, then an SSM Run Command applies migrations, provisions the app role
and **then** swaps the container (`docker compose up -d`, recreate strategy — migrations always
precede code, so they must be backwards-compatible). Then the smoke: the free `/health` loop, and one
paid generation on `fast` with `max_tokens: 1` — not retried, so a red smoke is re-run by a person,
not by the pipeline. A change to the registry is a rollout too: the running process never re-reads
it.

A provider the registry **adds** needs its secret to exist and hold a value before any container
runs the new registry — and the pipeline's own `terraform apply` creates the secret value-less in
the same run that starts the container, which would then fail its startup. So, before pushing:
`terraform -chdir=infra/envs/staging apply` by hand from the branch, fill the new
`holahost/staging/llm-client/<api_key_ref>` with `put-secret-value`, then push the rollout.

**4. Rollback**

Redeploy the previous image digest via SSM Run Command: the exports and the last command of "Rolling
out by hand" with `IMAGE=<previous digest>`. If the last migration is irreversible, restore the
database from a snapshot rather than running `alembic downgrade`. A rollback also rolls back the
registry baked into the image.

**5. Rotate a DB password**

```bash
aws secretsmanager put-secret-value \
  --secret-id holahost/staging/llm-client/db-password \
  --secret-string '<new-password>'
# then REDEPLOY — a restart is not enough.
```

The deploy's provisioning step (`app/scripts/provision_app_role.py`) is the only thing that applies
the new value to the Postgres role: the `postgres` image sets a password at initdb only, and `pgdata`
outlives every restart. Restarting `api` without redeploying changes only which password the client
offers, and every connection then fails.

Rotating `db-superuser-password` needs an explicit
`docker exec -it llm-client-postgres-1 psql -U postgres -c "ALTER ROLE postgres PASSWORD '<new>'"`
**before** the secret is updated, or the next deploy loses its own access. Plain `docker` rather
than `docker compose`: a compose command loads the compose file, which refuses to run without
`IMAGE` and `POSTGRES_SUPERUSER_PASSWORD` set.

**6. Rotate a provider key — a restart, not a rollout**

The framework specification counts a key held at an external provider among the secrets whose
rotation completes on a rollout. Here a restart is enough, because the vendor holds the old and the
new key side by side while both are valid, and this service reads its key once, at process start.
What makes the restart safe is the order:

```bash
# 1. Create the new key in the vendor's console; keep the old one active.
# 2. Store it.
aws secretsmanager put-secret-value \
  --secret-id holahost/staging/llm-client/anthropic-api-key \
  --secret-string '<new key>'
# 3. Restart the api container on the instance (SSM Run Command). Plain `docker`, which needs no
#    compose variables; the process restarts and bootstrap re-reads Secrets Manager:
docker restart llm-client-api-1
# 4. One control generation, as in "Check"; op_completed must show outcome "success".
# 5. Only now revoke the old key in the vendor's console.
```

Revoking first takes the platform's whole LLM path down until the restart: a revoked key is a
request the vendor rejects, answered `500` on every generation. No image rollout is needed.

---

## prod

Identical to staging — its own `infra/envs/prod/` root and `.env` (prod's budget ceilings: ten times
staging's), the secrets under `holahost/prod/llm-client/`, `https://hola.host/api/llm-client/health`,
log group `/holahost/prod/llm-client`, dashboard `llm-client-prod` — with two differences:

- Nothing is promoted before a successful staging smoke.
- The `promote-prod` pipeline, triggered by an `llm-client/v*` tag, **resolves** the already-built
  image by the tagged commit's `git-<sha>` instead of rebuilding, and gates on a manual
  `environment: prod` approval before anything else runs. After the prod smoke passes it tags that
  exact digest `release-v<version>`.

**1. Deploy from scratch:** the same apply / fill-secrets / confirm-SNS sequence as staging, against
`infra/envs/prod`. The first deploy is pipeline-driven (tag push), not manual.

**2. Check:** `curl https://hola.host/api/llm-client/health`, then one paid generation, once; log group
`/holahost/prod/llm-client`; alarms `llm-client-prod-*`.

**3. Update:** tag `llm-client/vYYYYMMDD.N` on the `release/v*` commit that passed staging — the
release-branch commit, not the `main` merge commit: a squash merge lands on `main` as a new commit
object whose sha never existed on the release branch, so no `git-<sha>` image was built for it.

**4. Rollback:** as in staging.

**5–6. Rotation:** as in staging, against the `holahost/prod/llm-client/` secrets.

---

## Prerequisites outside this service's Terraform

**Logs.** The `api` container logs through Docker's `awslogs` driver straight into
`/holahost/<env>/llm-client`. That needs `logs:CreateLogStream` and `logs:PutLogEvents` on the
instance role, which this service's Terraform cannot grant: its roots own the log group, filters and
alarms, and neither owns compute or IAM. Until the permission exists the container will not start on
staging or prod — `docker compose up -d` fails with a `ResourceNotFoundException` or
`AccessDeniedException` from the driver, visible in the SSM command output.

**Secrets Manager read.** The same instance role reads this service's secrets at startup. It is one
role for every container on the instance, so nothing but convention keeps another service from
reading the provider keys; isolating them needs a role per service, a platform-level change.

**Outgoing HTTPS.** The only service on the platform that calls the internet: to the providers'
domains. When egress filtering appears, the domain list follows from the registry.

**The paid smoke's client.** The pipelines generate through the service as an ordinary caller: a
client registered in auth's config with `llm-client` among its allowed audiences, its credentials
stored as `LLM_CLIENT_SMOKE_CLIENT_ID` / `LLM_CLIENT_SMOKE_CLIENT_SECRET` in the GitHub environments
`staging` and `prod`. Until they are set the pipelines skip the paid call with a notice and check
`/health` only — a rollout then proves the process is up, not that it can generate, so check by hand
as in "Check".

## Access

Staging and prod use GitHub OIDC — no long-lived AWS keys. `deploy-staging` and `promote-prod`
assume per-environment IAM roles scoped to their trigger (the `release/v*` branch and the
`llm-client/v*` tag respectively); neither role can read a provider key. Manual console access
follows the platform's IAM and MFA policy, which is outside this service's scope.
