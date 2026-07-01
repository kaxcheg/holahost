# hola.host — Environment Runbook

Operational runbook for provisioning and operating hola.host environments (dev / staging / prod). Built
incrementally: **I-03** (AWS account bootstrap) and **I-04** (Terraform backend) are below; the full
per-environment deploy / rollback / smoke / rotation procedures are completed in **I-15**.

Context: serverless on a **single AWS account**; environments isolated by the name-prefix
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

## Local dev (no AWS / Terraform needed)

Prereqs: Docker + Compose, Python 3.12 + Poetry, Node ≥ 20 (versions pinned in `.tool-versions`). Dev
needs no AWS account and no Terraform — those are staging/prod only (I-03/I-04 below).

```bash
# 0. Create the local env file from the committed template, then fill it in. The live `<env>.env` is
#    gitignored (machine-local); `.env.example` is the committed template (all vars; secrets blank).
cp infra/envs/dev/.env.example infra/envs/dev/dev.env
#    Then edit infra/envs/dev/dev.env: for the compose stack set
#    DATABASE_URL=postgresql://holahost:holahost@postgres:5432/holahost ; IP_HASH_SALT + RESEND_API_KEY may be
#    any dev-local values (dev email goes to Mailpit). Leave SAMPLE_SERVER_API_KEY empty — `make dev-up` asks.

# 1. Bring up the stack — `make dev-up` prompts for SAMPLE_SERVER_API_KEY (a low-budget Anthropic key); or
#    `export SAMPLE_SERVER_API_KEY=…` beforehand. Then apply the schema:
make dev-up              # postgres + mailpit + api (Lambda RIE)
make migrate-dev         # alembic upgrade head against the compose Postgres
# 2. Frontend dev-server runs separately on the host (HTTP, hot reload):
npm run dev --prefix frontend
make dev-down            # stop the stack (make dev-down-v also wipes the DB volume)
```

Mailpit UI: <http://localhost:8025> · API (RIE invoke): <http://localhost:9000> · frontend: <http://localhost:5173>

---

## I-03 — AWS account + admin IAM user (one-time, manual)

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

---

## I-04 — Terraform backend: S3 state bucket (one-time, manual)

Terraform ≥ 1.10 uses **native S3 state locking** (`use_lockfile = true`, set in each env's
`infra/envs/<env>/backend.tf`). **No DynamoDB lock table is needed** — DynamoDB-based locking is
deprecated. Bucket **versioning** is what makes the state + lock safe; keep it enabled.

Create one state bucket per environment (as the `holahost` admin profile):

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

Once the buckets exist, initialise each environment against its real backend. Terraform reads the AWS
**deploy** region from the `AWS_REGION` env var (no region in tfvars). This deploy region is distinct
from the app's own boto region `AWS_RESOURCES_REGION` (a Settings field) — the two can differ:

```bash
export AWS_PROFILE=holahost
export AWS_REGION=us-east-1
cd infra/envs/staging && terraform init     # then: terraform plan / apply
cd infra/envs/prod    && terraform init
```

The IAM principal running Terraform needs, on each state bucket: `s3:ListBucket` and
`s3:GetObject` / `s3:PutObject` / `s3:DeleteObject`. With native locking, Terraform writes/reads the
lock object under the same state key (`<key>.tflock`) automatically — no extra resource or permission.

---

## Next (I-15)

The full Environment runbook — per-env deploy sequence, post-deploy smoke checks, rollback (image tag /
S3 version / Alembic revision), secret rotation, and access procedures — is completed in **I-15**,
building on the sections above.
