# hola.host — Environment Runbook

Operational runbook for provisioning and operating hola.host environments, organised **per environment**
(`dev` / `staging` / `prod`, spec §12.4). Built incrementally: shared one-time bootstrap (AWS account I-03,
Terraform backend I-04) and the `sm` secrets module (I-06 / I-07) are covered below; the full staging/prod
deploy · smoke · rollback · rotation steps land in **I-15**.

Context: serverless on a **single AWS account**; staging/prod isolated by the name-prefix
`holahost-{env}-*`, separate Terraform state, and separate IAM deploy roles (spec §12).

## Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| AWS CLI | v2 | account + manual bootstrap |
| Terraform | ≥ 1.10 | IaC (`infra/`); native S3 state locking |
| Docker + Compose | v2 | local dev stack, backend image build |
| Python + Poetry | 3.12 | backend |
| Node | ≥ 20 | frontend |

One-time external accounts (spec §12.4): AWS, Neon (Postgres), Resend (email), Sentry (errors), the
`hola.host` domain.

## Shared one-time setup (staging + prod)

Chicken-and-egg resources created **once** and used by both cloud environments. Do these before the
`staging` / `prod` sections.

### 1. AWS account + admin IAM user (I-03, manual)

A single AWS account hosts both staging and prod (spec §12.0). Deploys run through GitHub OIDC roles
(C-08) — the admin user below is for **one-time bootstrap and break-glass only**.

```bash
# 1. Create the AWS account via the console (root email + MFA on the root user). Then, signed in as
#    root (or an existing admin), create the admin IAM user:
aws iam create-user --user-name holahost-admin
aws iam attach-user-policy --user-name holahost-admin \
  --policy-arn arn:aws:iam::aws:policy/AdministratorAccess

# 2. Enable a virtual MFA device for holahost-admin:
#    Console → IAM → Users → holahost-admin → Security credentials → Assign MFA device (virtual).

# 3. Create a CLI access key and configure the local profile:
aws iam create-access-key --user-name holahost-admin
aws configure --profile holahost          # paste Access key / Secret; region = us-east-1; output = json

# 4. Verify:
aws sts get-caller-identity --profile holahost
```

> Modern alternative: AWS IAM Identity Center (SSO) instead of a long-lived IAM user — preferred if you
> already use it. The rest of this runbook only assumes a working `holahost` CLI profile.

### 2. Terraform backend — S3 state buckets (I-04, manual)

Terraform ≥ 1.10 uses **native S3 state locking** (`use_lockfile = true`, set in each env's
`infra/envs/<env>/backend.tf`). **No DynamoDB lock table is needed.** Bucket **versioning** is what makes
the state + lock safe; keep it enabled.

```bash
export AWS_PROFILE=holahost
REGION=us-east-1

for ENV in staging prod; do
  BUCKET="holahost-tfstate-$ENV"

  # us-east-1 needs no LocationConstraint (other regions do).
  aws s3api create-bucket --bucket "$BUCKET" --region "$REGION"

  aws s3api put-bucket-versioning --bucket "$BUCKET" \
    --versioning-configuration Status=Enabled

  aws s3api put-bucket-encryption --bucket "$BUCKET" \
    --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"aws:kms"}}]}'

  aws s3api put-public-access-block --bucket "$BUCKET" \
    --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
done
```

> S3 bucket names are globally unique. If `holahost-tfstate-<env>` is taken, append a short account
> suffix (e.g. `holahost-tfstate-<env>-<account-id>`) and update the `bucket` value in the matching
> `infra/envs/<env>/backend.tf`.

The IAM principal running Terraform needs, on each state bucket: `s3:ListBucket` and
`s3:GetObject` / `s3:PutObject` / `s3:DeleteObject`. With native locking, Terraform writes/reads the lock
object under the same state key (`<key>.tflock`) automatically — no extra resource or permission.

### 3. Neon project (I-07, manual)

Create the Neon project `holahost` in the Neon console (outside Terraform, §2.6). The per-env **branches**
(`staging`, `prod`) and their connection strings are created in the env sections below.

---

## dev — local stack (no AWS / Terraform)

Docker-compose stack (Postgres + Mailpit + Lambda RIE); needs no AWS account and no Terraform. Tool
versions pinned in `.tool-versions`.

1. **Create the local env file** from the committed template, then fill it in. The live `dev.env` is
   gitignored (machine-local); `.env.example` is the committed template (all vars; secrets blank).
   ```bash
   cp infra/envs/dev/.env.example infra/envs/dev/dev.env
   # Edit infra/envs/dev/dev.env: for the compose stack set
   #   DATABASE_URL=postgresql://holahost:holahost@postgres:5432/holahost
   # IP_HASH_SALT + RESEND_API_KEY may be any dev-local values (dev email goes to Mailpit).
   # Leave SAMPLE_SERVER_API_KEY empty — `make dev-up` asks for it.
   ```
2. **Bring up the stack + apply the schema.** `make dev-up` prompts for `SAMPLE_SERVER_API_KEY` (a
   low-budget Anthropic key), or `export SAMPLE_SERVER_API_KEY=…` beforehand.
   ```bash
   make dev-up          # postgres + mailpit + api (Lambda RIE)
   make migrate-dev     # alembic upgrade head against the compose Postgres
   ```
3. **Frontend dev-server** runs separately on the host (HTTP, hot reload):
   ```bash
   npm run dev --prefix frontend
   make dev-down        # stop the stack (make dev-down-v also wipes the DB volume)
   ```

Mailpit UI: <http://localhost:8025> · API (RIE invoke): <http://localhost:9000> · frontend: <http://localhost:5173>

---

## staging

Terraform deploys into the region set by `aws_region` in this env's `terraform.tfvars` (`us-east-1`); run the
`aws` CLI commands below in that same region (`export AWS_PROFILE=holahost AWS_REGION=us-east-1`). The app's
`AWS_RESOURCES_REGION` — the region its cold-start boto client uses for Secrets Manager — is **injected by
Terraform equal to `aws_region`** (in the `lambda` module, I-12), so the app always reads from its own deploy
region (§12.3).

1. **Terraform init + apply.** Provisions the staging resources defined so far — currently the `sm`
   module: four **value-less** secret containers
   `holahost/staging/{database_url,resend_api_key,ip_hash_salt,sample_server_api_key}`
   (`recovery_window_in_days = 0` → a deleted secret recreates immediately). No values are stored by
   Terraform (§10.3).
   ```bash
   cd infra/envs/staging
   terraform init
   terraform apply
   ```
   *(The `ecr`, `s3_frontend`, `route53`, `cloudfront`, `lambda`, `observability` modules are added to
   this env in I-08 … I-14; their apply/deploy steps land in I-15.)*
2. **Neon `staging` branch → connection string** (manual). In the Neon console create branch `staging`
   under project `holahost`, copy its **pooled** connection string (host contains `-pooler`):
   `postgresql://<user>:<pass>@<host>-pooler.<region>.aws.neon.tech/<db>?sslmode=require`. Store the plain
   `postgresql://` form — the app rewrites it to `postgresql+psycopg://` (`postgres_uow.py`).
3. **Populate the four secret values** (manual — all hand-entered):
   ```bash
   # database_url — the Neon staging pooled string from step 2:
   aws secretsmanager put-secret-value --secret-id holahost/staging/database_url \
     --secret-string 'postgresql://…-pooler…/neondb?sslmode=require'

   # ip_hash_salt — generate once; NEVER rotate (rotation invalidates rate_limit_counters, §10.5):
   aws secretsmanager put-secret-value --secret-id holahost/staging/ip_hash_salt \
     --secret-string "$(openssl rand -hex 32)"

   # sample_server_api_key — low-budget Anthropic key for the sample flow (server-side):
   aws secretsmanager put-secret-value --secret-id holahost/staging/sample_server_api_key \
     --secret-string 'sk-ant-…'

   # resend_api_key — left empty here; populated in I-16 (Resend account + domain verification).
   ```

*(Deploy image / frontend bundle / post-deploy smoke / rollback — I-15.)*

---

## prod

Same shape as `staging` (same `AWS_PROFILE` / `AWS_REGION` exports), with a separate Neon branch and
`recovery_window_in_days = 30`.

1. **Terraform init + apply.** Provisions
   `holahost/prod/{database_url,resend_api_key,ip_hash_salt,sample_server_api_key}` (value-less;
   `recovery_window_in_days = 30` → 30-day recovery window before permanent deletion).
   ```bash
   cd infra/envs/prod
   terraform init
   terraform apply
   ```
2. **Neon `prod` branch → connection string** (manual). Create branch `prod`, copy its **pooled**
   connection string (same `-pooler` form as staging). Store the plain `postgresql://` form.
3. **Populate the four secret values** (manual):
   ```bash
   # database_url — the Neon prod pooled string from step 2:
   aws secretsmanager put-secret-value --secret-id holahost/prod/database_url \
     --secret-string 'postgresql://…-pooler…/neondb?sslmode=require'

   # ip_hash_salt — generate once; NEVER rotate (§10.5):
   aws secretsmanager put-secret-value --secret-id holahost/prod/ip_hash_salt \
     --secret-string "$(openssl rand -hex 32)"

   # sample_server_api_key — production Anthropic key for the sample flow (server-side):
   aws secretsmanager put-secret-value --secret-id holahost/prod/sample_server_api_key \
     --secret-string 'sk-ant-…'

   # resend_api_key — left empty here; populated in I-16.
   ```

> **Recreate a secret that is still inside its recovery window** (prod, or staging if the window is > 0):
> `aws secretsmanager delete-secret --secret-id holahost/<env>/<key> --force-delete-without-recovery`, then re-apply.

*(Deploy image / frontend bundle / post-deploy smoke / rollback — I-15.)*

---

## Next (I-15)

The full Environment runbook — per-env deploy sequence (image build/push, frontend bundle, Alembic
migrate, Lambda update, CloudFront origin switch), post-deploy smoke checks, rollback (image tag /
S3 version / Alembic revision), secret rotation, and access procedures — is completed in **I-15**,
building on the sections above.
