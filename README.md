# hola.host

AI reply assistant for short-term-rental hosts: ingest a property guidebook, then generate grounded
answers to guest messages (RAG over the guidebook). Serverless on AWS (Lambda container behind
CloudFront), Postgres (Neon), Anthropic Claude. See [`docs/hola_host_spec.md`](docs/hola_host_spec.md)
for the full technical specification.

## Layout

```
backend/        Python 3.12 backend (clean architecture; poetry). Runs as an AWS Lambda container.
frontend/       Vite + TypeScript SPA (no framework). Tailwind v4.
infra/          Terraform (modules/ + envs/{staging,prod}/), the per-env non-secret config
                (envs/<env>/<env>.env — baked by the FE build, injected by TF), and the runbook.
docs/           Spec, OpenAPI contract, sample data, guidebook template.
```

Config model: `infra/envs/<env>/<env>.env` is the committed per-env config. Dev's holds the full backend
contract and is the docker-compose `env_file` + the frontend build source; staging/prod hold the shared
FE/BE keys (Terraform injects the full set; secrets live in AWS Secrets Manager, never committed).

## Local dev quickstart

Prereqs: Docker + Compose, Python 3.12 + Poetry, Node ≥20. (Full setup: [`infra/README.md`](infra/README.md).)

```bash
make dev-up                   # build the stack; prompts for SAMPLE_SERVER_API_KEY (low-budget Anthropic key)
make migrate-dev              # apply the DB schema to the compose Postgres
make dev-down                 # stop the stack
# Mailpit UI: http://localhost:8025 · API (RIE): http://localhost:9000 · FE: npm run dev --prefix frontend
```

## Common commands

```bash
make help          # list all targets
make test          # backend unit tests          make lint / typecheck / lint-imports
make fe-test       # frontend tests               make fe-build
make ci-local      # full local CI parity (§13.4)
make dev-test      # backend integration tests (testcontainers; needs Docker)
```

## Branching

GitFlow: feature/bugfix/chore/… branch off `develop` (squash-merge back); `release/v*` and
`hotfix/v*` → `main`. See `CONTRIBUTING.md` (added in C-02) and spec §13.0.
