# hola.host — Environment Runbook

Operational runbook for provisioning and operating hola.host environments, organised **per environment**
(`dev` / `staging` / `prod`, plus the `shared` and `repo` Terraform roots; spec §12.4). Covers the
one-time bootstrap (AWS account I-03, Terraform backend I-04, Neon I-07), every Terraform root
(`shared` / `repo` / `staging` / `prod` — modules I-06 … I-14), the manual deploy · smoke · rollback ·
access procedures (I-15), and the Resend email setup (I-16).

Context: serverless on a **single AWS account**; staging/prod isolated by the name-prefix
`holahost-{env}-*`, separate Terraform state, and separate IAM deploy roles (spec §12).

**Configuration.** Infra static config (region, bucket/domain names, per-env prefix/recovery/price/Lambda
sizing, data-file + system-prompt paths) lives in a single [`infra/config.yaml`](config.yaml), read by
every Terraform root (`yamldecode`);
modules receive it as explicit inputs. App runtime settings live in `infra/envs/<env>/<env>.env`. The
full app-vs-infra map (every setting → its single source) is spec **§10.9 Settings inventory**
([`docs/hola_host_spec.md`](../docs/hola_host_spec.md)).

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

for ENV in shared staging prod repo; do
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

The `repo` bucket backs the GitHub-settings root (`infra/envs/repo/`, I-14); the other three back the
same-named AWS roots.

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

## shared

Single-instance resources used by **both** cloud envs — the frontend S3 bucket `holahost-frontend`, the
Route 53 hosted zone `hola.host`, and the ACM certificate (us-east-1). Owned by a dedicated Terraform
root/state (`holahost-tfstate-shared`). **Apply this before `staging` / `prod`** — their configs read
these via data sources.

1. **Terraform init + apply.** Creates the private, versioned `holahost-frontend` bucket (OAC-only read)
   + its published objects (`config/template_schema.json`, `config/sample_guidebook.md`, and the per-env
   `system-prompt/<env>.md` seeds), the hosted zone `hola.host`, the ACM cert for `hola.host` +
   `staging.hola.host` (DNS-validated), and the single **ECR repo `holahost-api`** (I-08) that both envs
   deploy the API image to.
   ```bash
   cd infra/envs/shared
   terraform init
   terraform apply
   ```
2. **Delegate the domain to Route 53** (one-time). Copy the `route53_name_servers` output and set them as
   the NS records for `hola.host` at your domain registrar. ACM DNS-validation then completes
   automatically once the delegation propagates (minutes–hours); a follow-up `terraform apply` finishes
   `aws_acm_certificate_validation`.
   ```bash
   terraform output route53_name_servers
   ```
3. **Email DNS (SPF/DKIM/DMARC)** stays empty until Resend is configured: follow the
   **Resend (email) setup** section below (fills `email_dns_records` in `config.yaml`, re-applies
   this root).
4. **Push a bootstrap API image** (one-time, before the first per-env `lambda` apply — the `lambda`
   module creates its functions from `holahost-api:latest`, so that tag must exist first):
   ```bash
   ECR_URL=$(terraform output -raw ecr_repository_url)   # from infra/envs/shared
   aws ecr get-login-password --region eu-west-3 \
     | docker login --username AWS --password-stdin "${ECR_URL%%/*}"
   (cd ../../.. && docker build -f backend/Dockerfile -t "$ECR_URL:latest" .)   # build context = repo root
   docker push "$ECR_URL:latest"
   ```
   CI later replaces the running image per deploy via `update-function-code` (§13.5, I-15).

*(Per-env CloudFront distributions + Lambda functions are added in the `staging` / `prod` roots — see below.)*

---

## repo

GitHub repository settings (`infra/envs/repo/` → `github_repo` module, I-14): repo options, branch
protection for `main` / `develop`, and the GitHub Environments `staging` / `prod` (§13.7). A separate
root/state (`holahost-tfstate-repo`) — the repository is a single instance tied to neither AWS env.

1. **Create a fine-grained PAT** (GitHub → Settings → Developer settings → Fine-grained tokens):
   Repository access = `holahost` only; permissions **Administration: Read and write** +
   **Environments: Read and write**. Export it for the provider:
   ```bash
   export GITHUB_TOKEN=<fine-grained PAT>
   ```
2. **Init + import the pre-existing repo** (one-time — Terraform manages it, never creates it):
   ```bash
   cd infra/envs/repo
   terraform init
   terraform import module.github_repo.github_repository.this holahost
   ```
3. **Apply:**
   ```bash
   terraform apply
   ```
   ⚠️ The first apply **flips the repository private → public** (spec §10.3 assumes a public repo)
   and activates branch protection. Protection is **staged** (single-maintainer reality, ticket
   clarifications): PRs are required but approvals are not (`required_approving_review_count = 0`;
   raise to 1 per §13.7 once a second maintainer exists), required status checks land with CI (C-04),
   and `restrict_pushes` is intentionally not set — GitHub push restriction would also block PR merges.

---

## staging

Terraform deploys into the region set by `aws_region` in `infra/config.yaml` (`eu-west-3`); run the
`aws` CLI commands below in that same region (`export AWS_PROFILE=holahost AWS_REGION=eu-west-3`). The app's
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
   Also provisions this env's **Lambda functions** (`lambda` module: `holahost-staging-api` with a
   Function URL + the scheduled `holahost-staging-cleanup`, I-12) and its **CloudFront distribution**
   (`cloudfront` module: static + `/config/*` + `/api/*` → the Function URL) + the `staging.hola.host`
   alias record. It reads the shared bucket / zone / cert / **ECR repo** via data sources — so the
   **`shared` root must be applied first** and its bootstrap image pushed (shared step 4).
   And the env's **observability contour** (`observability` module, I-13): the
   `holahost-staging-alarms` SNS topic + email subscription, metric filters over the two Lambda log
   groups, and the four CloudWatch alarms (§10.2 / §10.5).
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

   # resend_api_key — left empty here; populated per the Resend section below (I-16).
   ```
4. **Confirm the SNS alarm subscription** (once per env): after the first apply, the `alert_email`
   inbox receives "AWS Notification - Subscription Confirmation" — click **Confirm subscription**.
   Alarms do not deliver until confirmed
   (check: `aws sns list-subscriptions-by-topic --topic-arn <holahost-staging-alarms ARN>` shows no
   `PendingConfirmation`).

### Deploy (manual, until CI C-06/C-07)

The manual mirror of the build-and-promote pipeline (§13.4 / §13.5): image → digest, migrate **before**
the code switch, both Lambdas by digest, frontend under a versioned prefix, CloudFront origin-path
switch, smoke.

```bash
export AWS_PROFILE=holahost AWS_REGION=eu-west-3
GIT_SHA=$(git rev-parse --short=12 HEAD)
ECR_URL=$(cd infra/envs/shared && terraform output -raw ecr_repository_url)

# 1. Backend image: build once, tag by commit, push, capture the immutable digest (§13.5).
aws ecr get-login-password --region eu-west-3 | docker login --username AWS --password-stdin "${ECR_URL%%/*}"
docker build -f backend/Dockerfile -t "$ECR_URL:git-$GIT_SHA" .
docker push "$ECR_URL:git-$GIT_SHA"
DIGEST=$(aws ecr describe-images --repository-name holahost-api \
  --image-ids imageTag=git-$GIT_SHA --query 'imageDetails[0].imageDigest' --output text)

# 2. DB migrate BEFORE the code switch (§13.5); DATABASE_URL from Secrets Manager.
export DATABASE_URL=$(aws secretsmanager get-secret-value \
  --secret-id holahost/staging/database_url --query SecretString --output text)
(cd backend && poetry run alembic upgrade head)

# 3. Lambda code switch — both functions, by digest (update-function-code is atomic).
for FN in holahost-staging-api holahost-staging-cleanup; do
  aws lambda update-function-code --function-name "$FN" --image-uri "$ECR_URL@$DIGEST"
done

# 4. Frontend bundle -> versioned release prefix (previous prefixes stay = rollback path).
npm run build:staging --prefix frontend
aws s3 sync frontend/dist/ "s3://holahost-frontend/releases/$GIT_SHA/"

# 5. CloudFront origin path -> the new release, then invalidate.
DIST_ID=$(aws cloudfront list-distributions --query \
  "DistributionList.Items[?Aliases.Items[0]=='staging.hola.host'].Id" --output text)
aws cloudfront get-distribution-config --id "$DIST_ID" > /tmp/cf.json
ETAG=$(jq -r .ETag /tmp/cf.json)
jq '.DistributionConfig | (.Origins.Items[] | select(.Id=="s3-releases").OriginPath) = "/releases/'$GIT_SHA'"' \
  /tmp/cf.json > /tmp/cf-new.json
aws cloudfront update-distribution --id "$DIST_ID" --if-match "$ETAG" \
  --distribution-config file:///tmp/cf-new.json
aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths "/*"

# 6. Smoke: static 200 + a live API round-trip (sample flow, no auth needed).
curl -fsS https://staging.hola.host/ >/dev/null && echo STATIC_OK
curl -fsS -X POST https://staging.hola.host/api/sample/generate \
  -H 'Content-Type: application/json' -d '{"message":"When is check-in?"}' | head -c 300
```

After the smoke, check CloudWatch (`/aws/lambda/holahost-staging-api`) for a fresh `INIT_START` and a
`http_request_completed` event with `status: 200`.

### Rollback

- **Backend**: point both functions at the previous digest (release prefixes / tags are never
  deleted; §13.5):
  ```bash
  aws ecr describe-images --repository-name holahost-api \
    --query 'sort_by(imageDetails,&imagePushedAt)[-5:].{tags:imageTags,digest:imageDigest}'
  for FN in holahost-staging-api holahost-staging-cleanup; do
    aws lambda update-function-code --function-name "$FN" --image-uri "$ECR_URL@<previous-digest>"
  done
  ```
- **Frontend**: switch the CloudFront `s3-releases` origin path back to the previous
  `releases/<git-sha>` prefix (deploy step 5 with the old sha) + invalidation.
- **DB**: `(cd backend && poetry run alembic downgrade -1)` for a reversible migration; for a
  destructive one — Neon PITR restore (prod retention 7 days, §13.5), then re-point
  `holahost/<env>/database_url` if the restore produced a new branch.

---

## prod

Same shape as `staging` (same `AWS_PROFILE` / `AWS_REGION` exports), with a separate Neon branch and
`recovery_window_in_days = 30`.

1. **Terraform init + apply.** Provisions
   `holahost/prod/{database_url,resend_api_key,ip_hash_salt,sample_server_api_key}` (value-less;
   `recovery_window_in_days = 30` → 30-day recovery window before permanent deletion), this env's
   **Lambda functions** (`holahost-prod-api` Function URL + `holahost-prod-cleanup`, I-12), plus its
   **CloudFront distribution** (static + `/config/*` + `/api/*`) + `hola.host` alias record (reads the
   shared bucket / zone / cert / **ECR repo** — the **`shared` root must be applied first**, bootstrap
   image pushed).
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

   # resend_api_key — left empty here; populated per the Resend section below (I-16).
   ```
4. **Confirm the SNS alarm subscription** — same as staging step 4, topic `holahost-prod-alarms`.

> **Recreate a secret that is still inside its recovery window** (prod, or staging if the window is > 0):
> `aws secretsmanager delete-secret --secret-id holahost/<env>/<key> --force-delete-without-recovery`, then re-apply.

### Deploy / rollback

Same procedure as the staging **Deploy** / **Rollback** sections with the prod substitutions:
secrets `holahost/prod/*`, functions `holahost-prod-api` / `holahost-prod-cleanup`, CloudFront alias
`hola.host`, frontend build `npm run build --prefix frontend` (prod mode). The frontend bucket and the
ECR repo are shared — a digest already validated on staging is promoted as-is (build-and-promote,
§13.5): skip deploy step 1 and reuse the staging digest + the same `releases/<git-sha>/` prefix.
Smoke: `curl -fsS https://hola.host/`.

---

## Access

Single-host model (§12.3): one project owner holds all credentials.

- **AWS**: the `holahost` CLI profile (bootstrap section 1). Staging access is self-serve; **prod
  secret values require MFA** — console reads of `holahost/prod/*` and the prod deploy role enforce
  it (§12.3). Deploys move to the GitHub OIDC roles with C-08 (no long-lived keys in CI).
- **GitHub**: `GITHUB_TOKEN` (fine-grained PAT, repo section) is needed **only** for the `repo` root —
  day-to-day git uses your normal credentials.
- **Neon / Resend / Sentry**: dashboard logins of the project owner; their machine-readable secrets
  live in Secrets Manager (`database_url`, `resend_api_key`) or env (`sentry_dsn`).

## Hot-updating a prompt / sample-guidebook / secret (force re-read)

The system prompt (`system-prompt/<env>.md`), the sample guidebook (`config/sample_guidebook.md`), and
the four Secrets Manager values are read once per **cold start** by `scripts/bootstrap.py` — a warm
Lambda container keeps the old value in memory. To apply a change **without a redeploy** (no image
rebuild, no `update-function-code`):

1. Update the source object / secret:
   ```bash
   export AWS_PROFILE=holahost AWS_REGION=eu-west-3
   # prompt (private, live-editable — s3_frontend's ignore_changes keeps Terraform from reverting it):
   aws s3 cp new_prompt.md s3://holahost-frontend/system-prompt/<env>.md
   # sample guidebook:
   aws s3 cp new_sample.md s3://holahost-frontend/config/sample_guidebook.md
   # a secret value:
   aws secretsmanager put-secret-value --secret-id holahost/<env>/<key> --secret-string '…'
   ```
2. Force every execution environment to recycle so the next invocations cold-start and re-read. A no-op
   **configuration** update does this — it is NOT an image redeploy:
   ```bash
   for FN in holahost-<env>-api holahost-<env>-cleanup; do
     aws lambda update-function-configuration \
       --function-name "$FN" --description "force cold start $(date -u +%FT%TZ)"
   done
   ```
3. Verify: the next request logs a fresh `INIT_START` in CloudWatch (`/aws/lambda/holahost-<env>-api`)
   and serves the new value. Warm containers not yet recycled drain naturally.

## Resend (email) setup (I-16, manual)

One-time email-provider setup (§10.7). Prerequisite: the `shared` root applied and the `hola.host`
zone delegated (shared step 2) — Resend verifies records against live DNS.

1. **Create the Resend account** and add the domain: Resend dashboard → Domains → Add domain →
   `hola.host` (pick the EU region). The dashboard shows the records to create (SPF TXT + MX on the
   send subdomain, DKIM TXT `resend._domainkey`).
2. **Copy the records into `infra/config.yaml` → `email_dns_records`** (keyed by a free-form label;
   `name` is the DNS record name — MX and SPF TXT share `send.hola.host`). Shapes below are examples,
   use the dashboard values verbatim; the DMARC monitoring policy is ours:
   ```yaml
   email_dns_records:
     send-mx:
       name: send.hola.host
       type: MX
       ttl: 300
       records: ["10 feedback-smtp.eu-west-1.amazonses.com"]
     send-spf:
       name: send.hola.host
       type: TXT
       ttl: 300
       records: ["v=spf1 include:amazonses.com ~all"]
     dkim:
       name: resend._domainkey.hola.host
       type: TXT
       ttl: 300
       records: ["p=<DKIM public key from the dashboard>"]
     dmarc:
       name: _dmarc.hola.host
       type: TXT
       ttl: 300
       records: ["v=DMARC1; p=none; rua=mailto:kaxcheg@gmail.com"]
   ```
3. **Apply the `shared` root** (owns the zone): `cd infra/envs/shared && terraform apply`.
4. **Verify** in the Resend dashboard (Domains → `hola.host` → Verify; propagation may take minutes).
5. **Create two API keys** (dashboard → API Keys): `holahost-staging` and `holahost-prod`, permission
   **Sending access** restricted to `hola.host`. Store each in Secrets Manager:
   ```bash
   aws secretsmanager put-secret-value --secret-id holahost/staging/resend_api_key --secret-string 're_…'
   aws secretsmanager put-secret-value --secret-id holahost/prod/resend_api_key    --secret-string 're_…'
   ```
   (then force a cold start per the hot-update section above if the env is already live).
6. **Check `RESEND_FROM`** in `infra/envs/staging/staging.env` / `infra/envs/prod/prod.env` — it must
   be an address on the verified domain (e.g. `no-reply@hola.host`).
