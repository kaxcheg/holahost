# Holahost

Holahost is a property-management app for short-term-rental hosts (calendar, pricing, guest
communication, …). This monorepo currently holds two things:

- **The Holahost frontend** — the web app (`holahost/frontend/`), owned by Holahost.
- **The `lead-capture` microservice** — a guest-message reply assistant (RAG over an STR guidebook)
  that powers the public lead-magnet demo: a host drops an email, gets a magic link, uploads a
  guidebook, and sees grounded answers to guest messages on their own data. It owns the `Lead`,
  `Guidebook`, and `Chunk` domain and runs serverless on AWS (Lambda container behind CloudFront,
  Postgres, Anthropic Claude). Backend + IaC live under `holahost/services/lead-capture/`.

The Holahost management app itself (calendar/pricing/comms) is described in
[`holahost/docs/holahost_overview.md`](holahost/docs/holahost_overview.md); the lead-capture
microservice's full technical specification is in
[`holahost/services/lead-capture/docs/lead_capture_spec.md`](holahost/services/lead-capture/docs/lead_capture_spec.md).

## Layout

```
holahost/                              the Holahost app
  frontend/                            Vite + TypeScript SPA (no framework). Tailwind v4.
  docs/                                Holahost product docs (overview + app-deploy sections).
  infra/                               Holahost PLATFORM Terraform: domain, frontend hosting, CDN/gateway,
                                       ECR registry, GitHub settings. Env roots:
                                       envs/{common, codebase, <env>/{capture-lead, gateway}}. + runbook.
  services/
    lead-capture/                      the lead-capture microservice
      backend/                         Python 3.12 backend (clean architecture; poetry). AWS Lambda container.
      infra/                           the service as an env-AGNOSTIC Terraform module (lambda/sm/observability);
                                       the app's env roots instantiate it (the app decides the environment).
      docs/                            Spec, OpenAPI contract, sample data, guidebook template, system prompts.

scripts/  Makefile  .pre-commit-config.yaml  docker-compose.yml  .dockerignore  .tool-versions
.github/  CONTRIBUTING.md              repo-global tooling (see ownership map)
```

### Ownership map

| Path | Owner |
|---|---|
| `holahost/frontend/` | Holahost app |
| `holahost/docs/` | Holahost app |
| `holahost/infra/` | Holahost app (platform: domain, hosting, gateway, ECR, GitHub) |
| `holahost/services/lead-capture/backend/` | lead-capture microservice |
| `holahost/services/lead-capture/infra/` | lead-capture microservice (Terraform module; the app deploys it) |
| `holahost/services/lead-capture/docs/` | lead-capture microservice |
| `.github/` | Holahost (repo-global; GitHub requires it at the repo root) |
| `scripts/`, `Makefile`, `.pre-commit-config.yaml`, `docker-compose.yml`, `.dockerignore`, `.tool-versions`, `CONTRIBUTING.md` | repo-global tooling |

The app HOSTS the service: the `common` root provisions the shared substrate (domain, frontend bucket,
ECR repo), each `<env>/capture-lead` root instantiates the service module (independently deployable),
and each `<env>/gateway` root is the app edge that mounts the service at `/api/capture-lead/*` (reading
the service's Function URL via `terraform_remote_state`). The frontend is a client of the service across
the ownership boundary (consumes its OpenAPI contract + published `/config/*` assets — see the
cross-references in `vite.config.ts`, `package.json`, `published-config-paths.test.ts`).

Config model: `holahost/services/lead-capture/envs/<env>.env` is the committed per-env backend config,
**owned by the capture-lead service** (not the platform). Dev's holds the full backend contract and is
the docker-compose `env_file` + the frontend build source; staging/prod hold the shared FE/BE keys (the
app's `capture-lead` root parses it and injects the non-secret set into the service Lambda; secrets live
in AWS Secrets Manager, never committed).

## Local dev quickstart

Prereqs: Docker + Compose, Python 3.12 + Poetry, Node ≥20. (Full setup:
[`holahost/infra/README.md`](holahost/infra/README.md).)

```bash
make dev-up                   # build the stack; prompts for SAMPLE_SERVER_API_KEY (low-budget Anthropic key)
make migrate-dev              # apply the DB schema to the compose Postgres
make dev-down                 # stop the stack
# Mailpit UI: http://localhost:8025 · API (RIE): http://localhost:9000 · FE: npm run dev --prefix holahost/frontend
```

## Common commands

```bash
make help          # list all targets
make hooks-install # one-time: install the git hooks (pre-commit + commit-msg, §13.3)
make test          # backend unit tests          make lint / typecheck / lint-imports
make fe-test       # frontend tests               make fe-build
make ci-local      # full local CI parity (§13.4)
make dev-test      # backend integration tests (testcontainers; needs Docker)
```

## Branching

GitFlow: feature/bugfix/chore/… branch off `develop` (squash-merge back); `release/v*` and
`hotfix/v*` → `main`. See [`CONTRIBUTING.md`](CONTRIBUTING.md) and the spec §13.0.
