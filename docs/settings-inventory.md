# Settings inventory — by consumer and source

Every configuration value in the project, grouped by its **consumer** (backend / frontend / infra);
each row names the **source** the value comes from. Destined for the spec (§10.2 Settings / §12.3).

## Sources

| Source | What it is |
|---|---|
| **be-env** | `infra/envs/<env>/<env>.env` — the per-env backend config file (dev: live, gitignored, + committed `.env.example`; staging/prod: values are Terraform-injected into the Lambda, I-12) |
| **fe-env** | `frontend/.env` — the frontend-owned config file (gitignored, + committed `frontend/.env.example`) |
| **config.yaml** | `infra/config.yaml` — the single source of truth for infra static config |
| **SM** | AWS Secrets Manager — the four secret *values* (staging/prod; out-of-IaC, §10.3). In dev they sit blank in be-env. |

A value's **source can differ from its consumer** — the backend consumes `frontend_origin` (from
config.yaml) and `magic_link_path` (from fe-env); the frontend consumes `ENV` (from be-env). Those are
the rows below where source ≠ consumer.

---

## 1 — Backend

Consumes the `app/config/config.py` `Settings` fields (full list in `config.py`) + a few raw env vars.

| Setting(s) | Source |
|---|---|
| `env`, `model_id_sample`/`model_id_real`, `embedding_model_name`, `system_prompt`, `anthropic_base_url`, `resend_from`, `haiku_output_price_per_mtok`, `allowed_mime_types`, all numeric size/rate/chunk/token limits + `*_timeout_seconds`, `magic_link_ttl_days`, `magic_link_token_bytes`, `cleanup_batch_size`, `sample_guidebook_path` (dev only) | **be-env** |
| `database_url`, `resend_api_key`, `ip_hash_salt`, `sample_server_api_key` | **SM** (dev: be-env, blank) |
| `frontend_origin` (← config.yaml `domain`/`subdomain`), `aws_resources_region` (← config.yaml `aws_region`), `sample_guidebook_s3_bucket` (← config.yaml `frontend_bucket`) | **config.yaml** — Terraform computes + injects (I-12) |
| `sample_guidebook_s3_key` | **`s3_frontend`** module — the published object's key (`config/sample_guidebook.md`, `sample_guidebook_key` output); Terraform injects (I-12) |
| `magic_link_path`, `magic_link_url_param` | **fe-env** — dev: docker-compose 2nd `env_file`; staging/prod: Terraform injects (I-12) |
| `SMTP_HOST`/`SMTP_PORT` (dev only) | be-env |
| `FASTEMBED_CACHE_PATH` | Docker image `ENV` (constant) |
| `AWS_REGION` | Lambda runtime (reserved; not app-read) |

> Each of these has its **single source of value** in config.yaml (or `s3_frontend` for the object key) —
> **no literal is duplicated** in staging/prod be-env (all removed; Terraform injects them at deploy, I-12).
> In **dev** `frontend_origin` genuinely lives in be-env (`http://localhost:5173` — its own single source, no
> Terraform); `sample_guidebook_s3_*` are unset in dev (the backend reads the local `sample_guidebook_path`).

## 2 — Frontend

Consumes `src/config.ts` values, baked into the bundle at `vite build`.

| Setting | Source |
|---|---|
| `ENV`, `API_BASE_URL` | **be-env** |
| `MAGIC_LINK_URL_PARAM`, `MAGIC_LINK_PATH` | **fe-env** |

(vite bakes each into the bundle as `import.meta.env.*`; the frontend reads `MAGIC_LINK_URL_PARAM` to pull
`?<param>=` and `MAGIC_LINK_PATH` to scope the magic-link landing — `boot/magic-link-landing`.)

## 3 — Infra (Terraform)

Consumes root/module inputs.

| Setting | Source |
|---|---|
| `aws_region`, `project`, `frontend_bucket`, `domain`, `email_dns_records`, `guidebook_template_path`, `sample_guidebook_path`, and per-env `name_prefix` / `subdomain` / `recovery_window_in_days` / `price_class` | **config.yaml** |
| `secret_keys` (the SM secret names) | backend `sm_loader.SERVER_SIDE_SECRET_KEYS` — infra mirrors the contract (a module default synced by hand) |
| the published objects themselves — `docs/guidebook_template.json` + `docs/sample_guidebook.md` (`s3_frontend` publishes as `config/template_schema.json` / `config/sample_guidebook.md`; their **paths** come from config.yaml `guidebook_template_path`/`sample_guidebook_path`) | app data files |
| state-bucket names `holahost-tfstate-{shared,staging,prod}` | literals in each `backend.tf` (Terraform forbids interpolation in the backend block) |
| CSP / security-header values | `cloudfront` module constants (§10.3, verbatim) |

---

## Single-source, no hand-sync

The cross-consumer values each have **one** source of truth; Terraform relays them so there is no
duplicated literal to keep in sync (the exception is `secret_keys`, mirrored by hand from the backend
contract):

- infra-owned, consumed by the backend (`frontend_origin`, `aws_resources_region`,
  `sample_guidebook_s3_bucket`) → **config.yaml**; `sample_guidebook_s3_key` → **`s3_frontend`** object key.
  All TF-injected (I-12) — no literal duplicated in staging/prod be-env.
- frontend-owned, consumed by **both** the frontend (landing) and the backend (link build)
  (`magic_link_path`, `magic_link_url_param`) → **fe-env**; the frontend bakes them at build, the backend
  gets them via docker-compose (dev) / TF (staging/prod, I-12).
- `AWS_REGION` (Lambda runtime, deploy region) numerically equals config.yaml `aws_region` but is a
  separate reserved channel — not app-read, distinct from `aws_resources_region`.
