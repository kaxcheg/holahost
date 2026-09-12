# Holahost

A property-management platform for short-term-rental hosts — calendar, pricing, guest communication
— built as a microservice monorepo on AWS: Docker Compose services on a shared network behind an API
Gateway, each one an independent deploy unit.

The architecture, the contract every microservice satisfies and the shared libraries are described
in [`holahost/README.md`](holahost/README.md).

## Layout

```
holahost/
  services/<svc>/     backend microservices
  libs/<lib>/         shared platform libraries (path dependencies, not published)
  tools/<tool>/       console tools — not deploy units
  templates/service/  the skeleton a new service is copied from
  infra/modules/      Terraform modules the services' own roots call
  make/common.mk      make targets every service includes
.github/  .pre-commit-config.yaml  .tool-versions  CONTRIBUTING.md
```

## What is here

| Component | State |
|---|---|
| [`holahost-observability`](holahost/libs/holahost-observability/README.md), [`holahost-http`](holahost/libs/holahost-http/README.md), [`holahost-auth`](holahost/libs/holahost-auth/README.md), [`holahost-db`](holahost/libs/holahost-db/README.md) | implemented |
| [`rag-documents`](holahost/services/rag-documents/README.md) — document ingestion and vector search | implemented, with CI/CD and Terraform |
| [`templates/service`](holahost/templates/service/README.md) — new-service skeleton | implemented |
| `infra/modules` — `service-ecr`, `service-observability` | implemented |
| [`llm-client`](holahost/services/llm-client/README.md) — facade over external LLM providers | designed, not built |
| [`guest-reply`](holahost/tools/guest-reply/README.md) — console orchestrator | designed, not built |
| `auth` — JWT issuer; platform Terraform root; web frontend | designed, not built |

Nothing here is deployed yet: the Terraform roots describe infrastructure that has not been applied
outside local development.

## Getting started

Toolchain versions are pinned in `.tool-versions` (Python, Poetry, Terraform) and are the same ones
the Docker images and CI use.

```bash
make hooks-install                      # one-time: install the pre-commit and commit-msg hooks

cd holahost/services/rag-documents
make dev-up                             # build, migrate, start the service and its Postgres
make ci-local                           # what CI runs: hooks, tests, the OpenAPI contract check
```

Each service documents its own operation in `docs/runbook.md` — deploying from scratch, verifying,
upgrading, rolling back, rotating secrets.

## Conventions

Branching, commit format, merge strategy, naming and the hook set are in
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## License

MIT — see [`LICENSE`](LICENSE).
